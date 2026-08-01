"""Migration Wave routes: batch-store planner output / list waves for an assessment."""

from typing import List

from fastapi import APIRouter, Depends, status

from app.dependencies.auth import require_assessment_owner
from app.dependencies.services import get_wave_service
from app.entities.wave import MigrationWave
from app.schemas_v1.envelope import success_envelope
from app.schemas_v1.wave import WaveCreateRequest, WaveResponse
from app.services_v1.wave_service import WaveService

router = APIRouter(tags=["Migration Waves"])


def _to_response(wave: MigrationWave) -> dict:
    return WaveResponse(
        wave_id=wave.id,
        assessment_id=wave.assessment_id,
        wave_number=wave.wave_number,
        components=wave.components,
        rationale=wave.rationale,
        risk_summary=wave.risk_summary,
        created_at=wave.created_at,
    ).model_dump(mode="json")


@router.post("/assessments/{assessment_id}/waves", status_code=status.HTTP_201_CREATED)
async def create_waves(
    assessment_id: str,
    payload: WaveCreateRequest,
    service: WaveService = Depends(get_wave_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Stores one or more planner-produced migration waves for an assessment.

    404s if the assessment does not exist; 409s if a wave_number already exists
    for this assessment (each wave_number must be unique per assessment).
    """
    waves = await service.create_waves(assessment_id, payload.waves)
    return success_envelope([_to_response(w) for w in waves], message="Migration waves stored successfully.")


@router.get("/assessments/{assessment_id}/waves")
async def list_waves(
    assessment_id: str,
    service: WaveService = Depends(get_wave_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Lists all migration waves stored for an assessment. 404s if the assessment does not exist."""
    waves: List[MigrationWave] = list(await service.list_waves(assessment_id))
    return success_envelope([_to_response(w) for w in waves], message="Migration waves retrieved successfully.")
