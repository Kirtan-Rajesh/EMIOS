"""Simulation Result routes: run / retrieve a per-assessment cascading-failure +
Monte Carlo simulation, scoped to that assessment's own persisted graph."""

from fastapi import APIRouter, Depends, status

from app.dependencies.auth import require_assessment_owner
from app.dependencies.services import get_simulate_service
from app.schemas_v1.envelope import success_envelope
from app.schemas_v1.simulate import SimulateRequest
from app.services_v1.simulate_service import SimulateService

router = APIRouter(tags=["Simulation"])


@router.post("/assessments/{assessment_id}/simulate", status_code=status.HTTP_201_CREATED)
async def run_simulation(
    assessment_id: str,
    payload: SimulateRequest,
    service: SimulateService = Depends(get_simulate_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Runs a cascading-failure + Monte Carlo simulation against the assessment's
    persisted graph and stores the result (upsert - rerunning replaces the prior
    result). 404s if the assessment does not exist; 400s if no graph has been
    posted for it yet."""
    result = await service.run_simulation(assessment_id, payload.target_id, payload.already_migrated)
    return success_envelope(result, message="Simulation completed and result stored successfully.")


@router.get("/assessments/{assessment_id}/simulate")
async def get_simulation(
    assessment_id: str,
    service: SimulateService = Depends(get_simulate_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Retrieves the most recent stored simulation result for an assessment. 404s
    if the assessment does not exist, or if no simulation has been run yet."""
    result = await service.get_simulation(assessment_id)
    return success_envelope(result, message="Simulation result retrieved successfully.")
