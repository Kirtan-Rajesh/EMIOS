"""Business logic for Document Discovery: turns an assessment's already-uploaded
documents (BRD, HLD, DB schema, ETL mappings, stored procedures, API specs,
metadata catalogs) into a persisted service dependency graph.

``run_discovery_stream()`` is the one real implementation - an async generator
that yields a progress event per pipeline step (useful for a streamed UI, see
app/api/v1/discovery.py's SSE route) and, as its last event, the same
completion payload the original one-shot ``run_discovery()`` returns.
``run_discovery()`` is kept as a thin wrapper around the generator so existing
non-streaming callers (scripts, tests) see an unchanged contract.

Reuses GraphService.persist_graph() as-is for the actual write (relational
tables + best-effort Neo4j sync) - this module's only job is producing the
GraphData that goes into it, and (as of the streaming rework) durably saving
that same data as nodes.csv/edges.csv via ObjectStorage for human inspection.
Nothing downstream (12-agent pipeline, simulation, wave planning) needs to
know or care that a graph came from document discovery instead of a CSV
upload; they consume the same ServiceNode/DependencyEdge shape either way.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from typing import Any, AsyncGenerator, Dict, List, Tuple

from starlette.concurrency import run_in_threadpool

from app.core.exceptions import BadRequestException, ResourceNotFoundException
from app.core.storage import ObjectStorage
from app.entities.assessment import Assessment
from app.models.schemas import DependencyEdge, GraphData, ServiceNode
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.upload_repository import UploadRepository
from app.services_v1.extraction.base import ExtractionResult
from app.services_v1.extraction.document_extraction_service import DocumentExtractionService
from app.services_v1.extraction.entity_resolution import merge_extraction_results
from app.services_v1.graph_service import GraphService

logger = logging.getLogger("emios")

# Same field order used by Northwind_Expected_Graph/generate_expected_graph.py,
# so a real /discover/stream run and that offline reference baseline are
# directly diffable row-for-row.
_NODE_CSV_FIELDS = [
    "id", "name", "type", "business_value", "revenue_impact", "migration_complexity",
    "base_cost", "base_duration", "status", "failure_probability", "runtime", "annual_cost",
]
_EDGE_CSV_FIELDS = ["source", "target", "type", "criticality", "is_discovered"]

# Semantic entity resolution (merge_extraction_results) makes real embedding +
# LLM calls with no internal timeout of its own - bound it here so a slow or
# unresponsive provider can't wedge an entire discovery run indefinitely.
_MERGE_TIMEOUT_SECONDS = 100


def _nodes_to_csv(nodes: List[ServiceNode]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_NODE_CSV_FIELDS)
    for n in nodes:
        d = n.model_dump()
        writer.writerow([d[f] for f in _NODE_CSV_FIELDS])
    return buf.getvalue()


def _edges_to_csv(edges: List[DependencyEdge]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_EDGE_CSV_FIELDS)
    for e in edges:
        d = e.model_dump()
        writer.writerow([d[f] for f in _EDGE_CSV_FIELDS])
    return buf.getvalue()


def _discovery_storage_key(assessment_id: str, filename: str) -> str:
    """Fixed (not UUID-randomized) key so each re-run overwrites the previous
    discovery CSVs for this assessment, mirroring GraphRepository.replace_graph's
    full-replace semantics rather than accumulating stale copies."""
    return f"assessments/{assessment_id}/discovery/{filename}"


class DiscoveryService:
    def __init__(
        self,
        upload_repo: UploadRepository,
        assessment_repo: AssessmentRepository,
        graph_service: GraphService,
    ):
        self.upload_repo = upload_repo
        self.assessment_repo = assessment_repo
        self.graph_service = graph_service
        self.storage = ObjectStorage()
        self.extraction_service = DocumentExtractionService()

    async def _require_assessment(self, assessment_id: str) -> Assessment:
        assessment = await self.assessment_repo.get_by_id(assessment_id)
        if assessment is None:
            raise ResourceNotFoundException(f"Assessment '{assessment_id}' was not found.")
        return assessment

    async def ensure_ready_for_discovery(self, assessment_id: str) -> None:
        """Raises ResourceNotFoundException / BadRequestException if discovery
        can't proceed for this assessment. Called eagerly by the streaming route
        (so a bad assessment_id/no-uploads case still gets a normal 404/400
        instead of a 200 stream that immediately errors) and again at the top
        of run_discovery_stream() so the generator is correct standalone too."""
        await self._require_assessment(assessment_id)
        uploads = await self.upload_repo.list_for_assessment(assessment_id)
        if not uploads:
            raise BadRequestException(
                f"No documents have been uploaded for assessment '{assessment_id}' yet. "
                f"POST /api/v1/assessments/{assessment_id}/uploads before running discovery."
            )

    async def get_discovery_csv(self, assessment_id: str, filename: str) -> bytes:
        """Reads back a nodes.csv/edges.csv previously written by a discovery
        run for this assessment (the csv_generated step in run_discovery_stream
        below) - independent of whether the SSE event that originally produced
        it is still around client-side. Raises ResourceNotFoundException if
        discovery has never successfully produced one for this assessment."""
        await self._require_assessment(assessment_id)
        try:
            return await run_in_threadpool(
                self.storage.get_bytes_by_key, _discovery_storage_key(assessment_id, filename)
            )
        except FileNotFoundError:
            raise ResourceNotFoundException(
                f"No {filename} found for assessment '{assessment_id}' - run Process Documents first."
            )

    async def run_discovery_stream(self, assessment_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        await self.ensure_ready_for_discovery(assessment_id)
        uploads = await self.upload_repo.list_for_assessment(assessment_id)

        documents: List[Tuple[str, bytes]] = []
        read_warnings: List[str] = []
        for upload in uploads:
            try:
                # get_bytes() is a blocking S3 GET (or local disk read) - offload to
                # the threadpool so it doesn't stall the event loop.
                content = await run_in_threadpool(self.storage.get_bytes, upload.storage_reference)
                documents.append((upload.filename, content))
            except Exception as ex:
                logger.warning(f"Could not read stored document '{upload.filename}' ({upload.id}): {ex}")
                read_warnings.append(f"Could not read '{upload.filename}' from storage: {ex}")

        yield {"type": "start", "assessment_id": assessment_id, "total_documents": len(documents)}

        try:
            all_results: List[ExtractionResult] = []
            for index, (filename, content) in enumerate(documents, start=1):
                yield {"type": "document_start", "filename": filename, "index": index, "total": len(documents)}
                # extract_document() parses the file and, for prose that no structured
                # extractor claims, makes a blocking LLM call - offload to the
                # threadpool so other requests aren't stalled for the duration.
                results = await run_in_threadpool(self.extraction_service.extract_document, filename, content)
                all_results.extend(results)
                for r in results:
                    yield {
                        "type": "document_result",
                        "filename": r.source_filename,
                        "extractor": r.extractor,
                        "nodes_found": len(r.nodes),
                        "edges_found": len(r.edges),
                        "confidence": r.confidence,
                        "warnings": r.warnings,
                    }

            yield {"type": "merging", "message": f"Merging {len(all_results)} extraction result(s) and resolving duplicate systems across documents..."}
            # merge_extraction_results() now does real embedding calls (and, for
            # ambiguous cases, an LLM call) for semantic entity resolution on top
            # of the free exact-name matching - no longer pure/CPU-only, so it
            # needs the same threadpool offload as the other blocking I/O above.
            # Bounded with a timeout: a slow/unresponsive embedding or LLM
            # provider must not be able to wedge the whole stream indefinitely -
            # on timeout, fall back to the fast, deterministic exact-match-only
            # mode (the same one Northwind_Expected_Graph/generate_expected_graph.py
            # always uses) so the run still completes rather than hanging forever.
            try:
                nodes, edges, merge_warnings = await asyncio.wait_for(
                    run_in_threadpool(merge_extraction_results, all_results), timeout=_MERGE_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Semantic entity resolution timed out after {_MERGE_TIMEOUT_SECONDS}s for "
                    f"assessment '{assessment_id}'; falling back to exact-match-only merging."
                )
                nodes, edges, merge_warnings = await run_in_threadpool(
                    merge_extraction_results, all_results, enable_semantic_merge=False
                )
                merge_warnings = merge_warnings + [
                    f"Semantic entity resolution timed out after {_MERGE_TIMEOUT_SECONDS}s and was skipped; "
                    f"results reflect exact-name matching only."
                ]
            warnings = read_warnings + merge_warnings
            overall_confidence = (
                round(sum(r.confidence for r in all_results) / len(all_results), 2) if all_results else 0.0
            )
            extraction_report = {
                "per_document": [
                    {
                        "filename": r.source_filename,
                        "extractor": r.extractor,
                        "nodes_found": len(r.nodes),
                        "edges_found": len(r.edges),
                        "confidence": r.confidence,
                    }
                    for r in all_results
                ],
                "overall_confidence": overall_confidence,
            }

            if not nodes:
                yield {
                    "type": "complete",
                    "assessment_id": assessment_id,
                    "status": "no_data_extracted",
                    "node_count": 0,
                    "edge_count": 0,
                    "graph_status": "",
                    "warnings": warnings,
                    "extraction_report": extraction_report,
                }
                return

            nodes_csv = _nodes_to_csv(nodes)
            edges_csv = _edges_to_csv(edges)
            await run_in_threadpool(
                self.storage.upload_bytes, _discovery_storage_key(assessment_id, "nodes.csv"),
                nodes_csv.encode("utf-8"), "text/csv",
            )
            await run_in_threadpool(
                self.storage.upload_bytes, _discovery_storage_key(assessment_id, "edges.csv"),
                edges_csv.encode("utf-8"), "text/csv",
            )
            yield {
                "type": "csv_generated",
                "node_count": len(nodes),
                "edge_count": len(edges),
                "nodes_csv": nodes_csv,
                "edges_csv": edges_csv,
            }

            yield {"type": "persisting", "message": "Writing digital twin graph..."}
            persist_result = await self.graph_service.persist_graph(
                assessment_id, GraphData(nodes=nodes, edges=edges)
            )

            yield {
                "type": "complete",
                "assessment_id": assessment_id,
                "status": "graph_updated",
                "node_count": persist_result["node_count"],
                "edge_count": persist_result["edge_count"],
                "graph_status": persist_result["graph_status"],
                "warnings": warnings,
                "extraction_report": extraction_report,
            }
        except Exception as ex:
            logger.exception(f"Document discovery failed mid-stream for assessment '{assessment_id}'")
            yield {"type": "error", "message": str(ex)}

    async def run_discovery(self, assessment_id: str) -> Dict[str, Any]:
        """Non-streaming entry point: drains run_discovery_stream() and returns
        the terminal event's payload. Preserves the original one-shot contract
        (same return shape as before the streaming rework) for callers that
        don't need progress - e.g. scripts, or a test asserting final state."""
        final_event: Dict[str, Any] = {}
        async for event in self.run_discovery_stream(assessment_id):
            if event["type"] in ("complete", "error"):
                final_event = event
        if final_event.get("type") == "error":
            raise BadRequestException(final_event["message"])
        final_event.pop("type", None)
        return final_event
