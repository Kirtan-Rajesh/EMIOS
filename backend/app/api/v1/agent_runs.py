"""Agent Run / Observability routes: run the multi-agent planner for an
assessment (recording one AgentRun row per negotiation stage) and list its
recorded runs."""

import json

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.dependencies.auth import require_assessment_owner
from app.dependencies.services import get_agent_run_service
from app.entities.agent_run import AgentRun
from app.schemas_v1.agent_run import AgentRunResponse
from app.schemas_v1.envelope import success_envelope
from app.services_v1.agent_run_service import AgentRunService

router = APIRouter(tags=["Agent Runs"])


def _to_response(run: AgentRun) -> dict:
    return AgentRunResponse(
        agent_run_id=run.id,
        assessment_id=run.assessment_id,
        agent_name=run.agent_name,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        summary=run.summary,
    ).model_dump(mode="json")


@router.post("/assessments/{assessment_id}/agent-runs", status_code=status.HTTP_201_CREATED)
async def run_planner(
    assessment_id: str,
    service: AgentRunService = Depends(get_agent_run_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Runs the Discovery/Dependency/Planner/Risk negotiation loop against the
    assessment's persisted graph, recording one AgentRun row per stage. 404s if
    the assessment does not exist; 400s if no graph has been posted for it yet."""
    result = await service.run_planner(assessment_id)
    return success_envelope(result, message="Agent planning run completed successfully.")


@router.post("/assessments/{assessment_id}/agent-runs/stream")
async def run_planner_stream(
    assessment_id: str,
    service: AgentRunService = Depends(get_agent_run_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Same negotiation loop as POST .../agent-runs, streamed as Server-Sent
    Events (`text/event-stream`) so a UI can show each agent's reasoning as
    it completes instead of a blocking spinner - useful since a multi-
    iteration negotiation (Risk objections send Planner back for another
    pass) can take a while. Each event is a JSON object on a `data: ` line;
    event `type`s are: start, agent_result (one per completed stage, in the
    same shape list_agent_runs() rows use), complete, error.

    Assessment-not-found / no-graph-yet are validated eagerly, before the
    stream begins, so those cases still return a normal 404/400 JSON error
    rather than a 200 stream that immediately emits an error event - once
    streaming starts the HTTP status is already committed, so any failure
    during negotiation instead becomes an in-stream
    {"type": "error", "message": ...} terminal event."""
    await service.ensure_ready_for_planner(assessment_id)

    async def event_source():
        async for event in service.run_planner_stream(assessment_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.get("/assessments/{assessment_id}/agent-runs/latest")
async def get_latest_planner_result(
    assessment_id: str,
    service: AgentRunService = Depends(get_agent_run_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Reconstructs the last completed planner run (same shape as POST
    .../agent-runs's response) from persisted AgentRun rows, without
    re-running anything - e.g. for the Planner page to show on mount whatever
    already completed, rather than requiring a fresh manual run every visit.
    `data` is null if the planner has never successfully completed for this
    assessment. 404s if the assessment does not exist."""
    result = await service.get_latest_result(assessment_id)
    return success_envelope(result, message="Latest planner result retrieved successfully.")


@router.get("/assessments/{assessment_id}/agent-runs")
async def list_agent_runs(
    assessment_id: str,
    service: AgentRunService = Depends(get_agent_run_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Lists all recorded agent-run stages for an assessment, newest first. 404s
    if the assessment does not exist."""
    runs = await service.list_agent_runs(assessment_id)
    return success_envelope([_to_response(r) for r in runs], message="Agent runs retrieved successfully.")
