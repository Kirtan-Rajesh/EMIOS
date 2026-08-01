"""Document Discovery routes: turn an assessment's already-uploaded documents
(BRD, HLD, DB schema, ETL mappings, stored procedures, API specs, metadata
catalogs) into a persisted service dependency graph."""

import json

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

from app.dependencies.auth import require_assessment_owner
from app.dependencies.services import get_discovery_service
from app.schemas_v1.discovery import DiscoveryResponse
from app.schemas_v1.envelope import success_envelope
from app.services_v1.discovery_service import DiscoveryService

router = APIRouter(tags=["Document Discovery"])


@router.post("/assessments/{assessment_id}/discover", status_code=status.HTTP_201_CREATED)
async def run_discovery(
    assessment_id: str,
    service: DiscoveryService = Depends(get_discovery_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Runs document discovery: reads every document already uploaded for this
    assessment, extracts systems/dependencies from each (DB schema and stored
    procedure dumps via SQL parsing, API specs via OpenAPI parsing, ETL
    mappings and metadata catalogs via CSV/XLSX parsing, and BRD/HLD prose via
    LLM extraction), merges and deduplicates the results, and persists the
    resulting graph via the same path a manual CSV upload uses. 404s if the
    assessment does not exist; 400s if no documents have been uploaded yet.

    This is the non-streaming variant (single response once everything has
    finished) - see POST .../discover/stream for a live-progress version of
    the exact same pipeline.
    """
    result = await service.run_discovery(assessment_id)
    response = DiscoveryResponse(**result)
    return success_envelope(response.model_dump(mode="json"), message="Document discovery completed successfully.")


@router.post("/assessments/{assessment_id}/discover/stream")
async def run_discovery_stream(
    assessment_id: str,
    service: DiscoveryService = Depends(get_discovery_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Same pipeline as POST .../discover, streamed as Server-Sent Events
    (`text/event-stream`) so a UI can show live per-document progress instead
    of a blocking spinner. Each event is a JSON object on a `data: ` line;
    event `type`s are: start, document_start, document_result, merging,
    csv_generated (carries the full nodes.csv/edges.csv text, also durably
    saved via ObjectStorage), persisting, complete, error.

    Assessment-not-found / no-uploads-yet are validated eagerly, before the
    stream begins, so those cases still return a normal 404/400 JSON error
    rather than a 200 stream that immediately emits an error event - once
    streaming starts the HTTP status is already committed, so any failure
    during extraction/merge/persist instead becomes an in-stream
    {"type": "error", "message": ...} terminal event.
    """
    await service.ensure_ready_for_discovery(assessment_id)

    async def event_source():
        async for event in service.run_discovery_stream(assessment_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.get("/assessments/{assessment_id}/discover/nodes.csv")
async def download_discovery_nodes_csv(
    assessment_id: str,
    service: DiscoveryService = Depends(get_discovery_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Downloads the nodes.csv from this assessment's most recent discovery
    run - durable, so it's fetchable any time after a successful run, not
    just while its originating SSE stream is still live client-side. Not
    envelope-wrapped (binary/text body), same pattern as the report PDF
    download. 404s if the assessment doesn't exist or discovery has never
    produced one."""
    content = await service.get_discovery_csv(assessment_id, "nodes.csv")
    return Response(
        content=content, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="nodes_{assessment_id}.csv"'},
    )


@router.get("/assessments/{assessment_id}/discover/edges.csv")
async def download_discovery_edges_csv(
    assessment_id: str,
    service: DiscoveryService = Depends(get_discovery_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Downloads the edges.csv from this assessment's most recent discovery
    run - see download_discovery_nodes_csv above."""
    content = await service.get_discovery_csv(assessment_id, "edges.csv")
    return Response(
        content=content, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="edges_{assessment_id}.csv"'},
    )
