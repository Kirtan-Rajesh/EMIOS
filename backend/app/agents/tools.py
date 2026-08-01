"""Agent tool definitions: gives Bedrock-backed agents (app/agents/workflow.py's
discovery_agent, app/services_v1/chat_service.py's ChatService.ask()) a way to
actively search this assessment's uploaded-document chunks and extracted
service/dependency graph, instead of getting one static context blob stuffed
into the prompt up front. See app.core.llm_provider.invoke_agentic() for the
tool_use loop that calls search_schema_graph() below through a caller-supplied
tool_executor.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("emios")

# Bedrock Converse API toolSpec for search_schema_graph - the schema an agent's
# system prompt shows the model so it knows the tool exists and how to call it.
SEARCH_SCHEMA_GRAPH_TOOL_SPEC: Dict[str, Any] = {
    "toolSpec": {
        "name": "search_schema_graph",
        "description": (
            "Searches this assessment's uploaded company documents and its extracted "
            "service/dependency graph for systems, databases, or facts matching a query. "
            "Use this when the context already provided doesn't cover something specific "
            "you need (a particular system's details, a fact that may be in an uploaded "
            "document) rather than guessing or fabricating an answer."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for, e.g. a system name or a topic to look up in the uploaded documents.",
                    },
                    "node_type": {
                        "type": "string",
                        "enum": ["Microservice", "Monolith", "Database", "Queue"],
                        "description": "Optional - restrict graph results to this node type.",
                    },
                },
                "required": ["query"],
            }
        },
    }
}


def search_schema_graph(
    query: str,
    services: List[Dict[str, Any]],
    dependencies: List[Dict[str, Any]],
    assessment_id: str = "",
    node_type: Optional[str] = None,
    top_k: int = 5,
) -> str:
    """Returns a formatted text block combining two sources, never raises (same
    degrade-gracefully style used throughout app/core and app/services):

    - Document-chunk RAG search over this assessment's uploads, via the same
      get_embedding_provider()/get_vector_store() calls used elsewhere for RAG
      retrieval (e.g. app/services_v1/chat_service.py's ChatService.ask()).
    - A lookup over the already-extracted `services`/`dependencies` (plain dicts, the
      same shape discovery_agent and chat_service.py already work with), filtered by
      `node_type` if given and by a case-insensitive substring match of `query`
      against each service's name.

    Returns a "no matches" string rather than "" on an empty result so a model calling
    this tool gets a clear signal to stop searching instead of retrying blindly.
    """
    sections: List[str] = []

    doc_matches = _search_document_chunks(query, assessment_id, top_k)
    if doc_matches:
        sections.append("Matching document excerpts:\n" + "\n".join(f"- {m}" for m in doc_matches))

    graph_matches = _search_graph_nodes(query, services, dependencies, node_type)
    if graph_matches:
        sections.append("Matching graph systems:\n" + "\n".join(f"- {m}" for m in graph_matches))

    if not sections:
        return f"No documents or graph systems matched '{query}'" + (f" (node_type={node_type})" if node_type else "") + "."
    return "\n\n".join(sections)


def _search_document_chunks(query: str, assessment_id: str, top_k: int) -> List[str]:
    if not assessment_id or not query:
        return []
    try:
        from app.core.embeddings import get_embedding_provider
        from app.services.vector_search_service import get_vector_store

        query_vector = get_embedding_provider().embed(query)
        results = get_vector_store().search(assessment_id, query_vector, top_k=top_k)
        return [r["text"] for r in results if r.get("text")]
    except Exception as ex:
        logger.warning(f"search_schema_graph document search failed for assessment '{assessment_id}': {ex}")
        return []


def _search_graph_nodes(
    query: str,
    services: List[Dict[str, Any]],
    dependencies: List[Dict[str, Any]],
    node_type: Optional[str],
) -> List[str]:
    try:
        query_lower = query.strip().lower()
        candidates = services
        if node_type:
            candidates = [s for s in candidates if s.get("type") == node_type]
        if query_lower:
            candidates = [s for s in candidates if query_lower in str(s.get("name", "")).lower()]

        if not candidates:
            return []

        dep_lines = []
        for s in candidates:
            sid = s.get("id")
            outbound = [e for e in dependencies if e.get("source") == sid]
            inbound = [e for e in dependencies if e.get("target") == sid]
            dep_summary = f"{len(outbound)} outbound / {len(inbound)} inbound dependencies"
            dep_lines.append(
                f"{s.get('name')} (type={s.get('type')}, business_value={s.get('business_value')}, "
                f"migration_complexity={s.get('migration_complexity')}, {dep_summary})"
            )
        return dep_lines
    except Exception as ex:
        logger.warning(f"search_schema_graph graph search failed: {ex}")
        return []
