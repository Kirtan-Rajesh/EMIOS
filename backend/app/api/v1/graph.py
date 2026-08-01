"""Assessment Graph Persistence routes: persist / retrieve a per-assessment
service dependency graph.

Router responsibilities only - business logic lives in GraphService. The request
body reuses ``app.models.schemas.GraphData`` (the same shape the legacy ingestion
pipeline accepts).
"""

from fastapi import APIRouter, Depends, status

from app.dependencies.auth import require_assessment_owner
from app.dependencies.services import get_graph_service
from app.models.schemas import GraphData
from app.schemas_v1.envelope import success_envelope
from app.schemas_v1.graph import GraphResponse
from app.services_v1.graph_service import GraphService

router = APIRouter(tags=["Assessment Graph"])


@router.post("/assessments/{assessment_id}/graph", status_code=status.HTTP_201_CREATED)
async def persist_graph(
    assessment_id: str,
    payload: GraphData,
    service: GraphService = Depends(get_graph_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Persists (full-replace) the service dependency graph for an assessment,
    and best-effort syncs it into the shared Neo4j digital twin store. 404s if
    the assessment does not exist."""
    result = await service.persist_graph(assessment_id, payload)
    return success_envelope(result, message="Assessment graph persisted successfully.")


@router.get("/assessments/{assessment_id}/graph")
async def get_graph(
    assessment_id: str,
    service: GraphService = Depends(get_graph_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Retrieves the persisted service dependency graph for an assessment. 404s
    if the assessment does not exist."""
    resolved_id, nodes, edges = await service.get_graph(assessment_id)
    response = GraphResponse(assessment_id=resolved_id, nodes=nodes, edges=edges)
    return success_envelope(response.model_dump(mode="json"), message="Assessment graph retrieved successfully.")
