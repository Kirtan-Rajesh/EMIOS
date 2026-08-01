"""Business logic for the per-assessment Document-grounded Chat module.

Retrieval-augmented: embeds the latest user message, searches this
assessment's own uploaded-document chunks (QdrantVectorStore, already scoped
per assessment_id - app/services/vector_search_service.py), combines that
with a compact summary of the assessment's digital twin graph/report/
simulation (whichever have been generated so far), and asks an LLM (via
app.core.llm_provider.invoke_agentic - the same provider chain every other
agent uses, plus a search_schema_graph tool call for anything this upfront
context doesn't cover) to answer grounded in that context.

Distinct from the legacy global POST /api/chat (app/api/endpoints.py,
run_copilot_chat in app/agents/workflow.py): that one reads a single shared
global graph and has no document retrieval at all - this one is scoped to one
assessment end to end and actually retrieves from the documents the user
uploaded for it, not just node/edge counts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from starlette.concurrency import run_in_threadpool

from app.agents import prompts
from app.agents.tools import SEARCH_SCHEMA_GRAPH_TOOL_SPEC, search_schema_graph
from app.core import observability
from app.core.embeddings import get_embedding_provider
from app.core.exceptions import ResourceNotFoundException
from app.core.llm_provider import invoke_agentic
from app.entities.assessment import Assessment
from app.models.schemas import DependencyEdge, ServiceNode
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.simulation_repository import SimulationRepository
from app.repositories.upload_repository import UploadRepository
from app.services.vector_search_service import get_vector_store
from app.services_v1.graph_service import to_dependency_edges, to_service_nodes

logger = logging.getLogger("emios")

_TOP_K_CHUNKS = 5
_MAX_HISTORY_MESSAGES = 6

# Caps on how much of the digital twin graph gets spelled out verbatim in the
# system prompt - generous enough to cover any real assessment's full topology
# (a "small enterprise migration" typically means dozens, not hundreds, of
# systems), while still bounding prompt size for the rare pathological case.
_MAX_GRAPH_SUMMARY_NODES = 80
_MAX_GRAPH_SUMMARY_EDGES = 150

# Used both when there's nothing at all to ground an answer in (no documents
# discovered, no chunks retrieved - asking the LLM to free-associate about a
# migration it knows nothing about would be worse than admitting that) and as
# invoke_agentic's fallback if no LLM provider is configured/reachable - matches
# LlmPromptExtractor's "never fabricate" convention.
_NO_CONTEXT_FALLBACK = (
    "I don't have enough information to answer that yet. Upload relevant documents and run "
    "Process Documents on the Documents tab so I have something to ground my answers in, and "
    "make sure an LLM provider is configured (see app/core/llm_provider.py) so I can actually "
    "reason over that context rather than just retrieve it."
)


def _build_graph_summary(service_nodes: List[ServiceNode], dependency_edges: List[DependencyEdge]) -> str:
    """Full (bounded) topology listing, not just a top-N-by-cost sample - so
    the copilot can actually answer questions about any system or dependency,
    not only the costliest ones."""
    if not service_nodes:
        return "No systems discovered yet - documents may not have been processed."

    shown_nodes = service_nodes[:_MAX_GRAPH_SUMMARY_NODES]
    node_lines = [
        f"- {n.name} ({n.type}, {n.business_value} business value, {n.migration_complexity} migration "
        f"complexity, ${n.annual_cost:,.0f}/yr hosting cost, ${n.revenue_impact:,.0f}/mo revenue impact)"
        for n in shown_nodes
    ]
    if len(service_nodes) > _MAX_GRAPH_SUMMARY_NODES:
        node_lines.append(f"... and {len(service_nodes) - _MAX_GRAPH_SUMMARY_NODES} more systems not listed here.")

    name_by_id = {n.id: n.name for n in service_nodes}
    shown_edges = dependency_edges[:_MAX_GRAPH_SUMMARY_EDGES]
    edge_lines = [
        f"- {name_by_id.get(e.source, e.source)} -> {name_by_id.get(e.target, e.target)} "
        f"({e.type}, {e.criticality} criticality)"
        for e in shown_edges
    ]
    if len(dependency_edges) > _MAX_GRAPH_SUMMARY_EDGES:
        edge_lines.append(f"... and {len(dependency_edges) - _MAX_GRAPH_SUMMARY_EDGES} more dependencies not listed here.")

    summary = "Systems:\n" + "\n".join(node_lines)
    summary += "\n\nDependencies:\n" + "\n".join(edge_lines) if edge_lines else "\n\nNo dependencies recorded."
    return summary


def _build_document_summary(uploads: List[Any]) -> str:
    """Lists every uploaded file by name, independent of RAG retrieval - so
    the copilot can answer meta-questions ("what have I uploaded?", "do you
    have the network diagram?") even when a specific question doesn't
    retrieve a relevant chunk from that document."""
    if not uploads:
        return "No documents have been uploaded for this assessment yet."
    return "Uploaded documents: " + ", ".join(f"{u.filename} ({u.source_type})" for u in uploads)


class ChatService:
    def __init__(
        self,
        assessment_repo: AssessmentRepository,
        graph_repo: GraphRepository,
        report_repo: ReportRepository,
        simulation_repo: SimulationRepository,
        upload_repo: UploadRepository,
    ):
        self.assessment_repo = assessment_repo
        self.graph_repo = graph_repo
        self.report_repo = report_repo
        self.simulation_repo = simulation_repo
        self.upload_repo = upload_repo

    async def _require_assessment(self, assessment_id: str) -> Assessment:
        assessment = await self.assessment_repo.get_by_id(assessment_id)
        if assessment is None:
            raise ResourceNotFoundException(f"Assessment '{assessment_id}' was not found.")
        return assessment

    async def ask(self, assessment_id: str, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        assessment = await self._require_assessment(assessment_id)
        last_user_message = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")

        # Retrieval: embed the question, search this assessment's own document
        # chunks. Both are blocking network calls - offload to the threadpool.
        retrieved_chunks: List[Dict[str, Any]] = []
        if last_user_message:
            try:
                query_vector = await run_in_threadpool(get_embedding_provider().embed, last_user_message)
                retrieved_chunks = await run_in_threadpool(
                    get_vector_store().search, assessment_id, query_vector, _TOP_K_CHUNKS
                )
            except Exception as ex:
                logger.warning(f"Chat retrieval failed for assessment '{assessment_id}': {ex}")

        nodes, edges = await self.graph_repo.get_graph(assessment_id)
        service_nodes = to_service_nodes(nodes)
        dependency_edges = to_dependency_edges(edges)

        if not retrieved_chunks and not service_nodes:
            return {"reply": _NO_CONTEXT_FALLBACK, "trace_id": None, "sources": []}

        report = await self.report_repo.get_by_assessment(assessment_id)
        simulation = await self.simulation_repo.get_by_assessment(assessment_id)
        uploads = await self.upload_repo.list_for_assessment(assessment_id)

        graph_summary = _build_graph_summary(service_nodes, dependency_edges)
        document_summary = _build_document_summary(uploads)

        report_summary = (
            f"Report on file: readiness score {report.readiness_score:.0f}/100. "
            f"Executive summary: {report.executive_summary}"
            if report
            else "No report has been generated for this assessment yet."
        )

        simulation_summary = (
            f"Latest what-if simulation: ${simulation.revenue_at_risk:,.0f}/mo revenue at risk, "
            f"${simulation.total_hosting_cost:,.0f}/yr current hosting cost, "
            f"${simulation.potential_savings:,.0f}/yr potential savings."
            if simulation
            else "No what-if simulation has been run for this assessment yet."
        )

        retrieved_context = (
            "\n\n".join(f"[{c.get('upload_id', 'unknown')}] {c.get('text', '')}" for c in retrieved_chunks)
            if retrieved_chunks
            else "No relevant document excerpts found for this question."
        )

        conversation_history = (
            "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages[:-1][-_MAX_HISTORY_MESSAGES:]
            )
            or "(no prior messages)"
        )

        sys_prompt = prompts.ASSESSMENT_CHAT_SYSTEM_PROMPT.format(
            customer_name=assessment.customer_name,
            project_name=assessment.project_name,
            target_cloud=assessment.target_cloud,
            node_count=len(service_nodes),
            edge_count=len(dependency_edges),
            graph_summary=graph_summary,
            document_summary=document_summary,
            report_summary=report_summary,
            simulation_summary=simulation_summary,
            retrieved_context=retrieved_context,
        )
        usr_prompt = prompts.ASSESSMENT_CHAT_USER_PROMPT.format(
            conversation_history=conversation_history,
            user_message=last_user_message,
        )

        # Lets the model follow up with a targeted search_schema_graph call for anything
        # the upfront retrieval/graph_summary above didn't cover (e.g. a system outside
        # _MAX_GRAPH_SUMMARY_NODES, or a document topic the top-K chunk search missed)
        # instead of answering "I don't know" or guessing - see app/agents/tools.py.
        services_dicts = [n.model_dump() for n in service_nodes]
        dependencies_dicts = [e.model_dump() for e in dependency_edges]

        def _search_tool_executor(tool_name: str, tool_input: Dict[str, Any]) -> str:
            return search_schema_graph(
                query=tool_input.get("query", ""),
                services=services_dicts,
                dependencies=dependencies_dicts,
                assessment_id=assessment_id,
                node_type=tool_input.get("node_type"),
            )

        reply_text = await run_in_threadpool(
            invoke_agentic, sys_prompt, usr_prompt, SEARCH_SCHEMA_GRAPH_TOOL_SPEC, _search_tool_executor,
            "Assessment Chat Copilot", _NO_CONTEXT_FALLBACK, assessment_id,
        )

        return {
            "reply": reply_text,
            "trace_id": observability.trace_metrics.get("last_trace_id"),
            "sources": sorted({c["upload_id"] for c in retrieved_chunks if c.get("upload_id")}),
        }
