"""Assessment Lifecycle routes: create / fetch / update-status.

Router responsibilities only - request validation is handled by the Pydantic
request models, all business logic lives in AssessmentService, all response
shaping is the small ``_to_response`` mapper below.
"""

from fastapi import APIRouter, Depends, status

from app.dependencies.auth import get_current_user
from app.dependencies.services import get_assessment_service
from app.entities.assessment import Assessment
from app.entities.user import User
from app.schemas_v1.assessment import (
    AssessmentCreateRequest,
    AssessmentResponse,
    AssessmentStatusUpdateRequest,
)
from app.schemas_v1.envelope import success_envelope
from app.services_v1.assessment_service import AssessmentService

router = APIRouter(tags=["Assessments"])


def _to_response(assessment: Assessment) -> dict:
    return AssessmentResponse(
        assessment_id=assessment.id,
        customer_name=assessment.customer_name,
        project_name=assessment.project_name,
        target_cloud=assessment.target_cloud,
        status=assessment.status,
        created_at=assessment.created_at,
        updated_at=assessment.updated_at,
    ).model_dump(mode="json")


@router.get("/assessments")
async def list_assessments(
    service: AssessmentService = Depends(get_assessment_service),
    current_user: User = Depends(get_current_user),
):
    """Lists the current user's own assessments, newest first."""
    assessments = await service.list_assessments(current_user.id)
    return success_envelope(
        [_to_response(a) for a in assessments],
        message="Assessments retrieved successfully.",
    )


@router.post("/assessments", status_code=status.HTTP_201_CREATED)
async def create_assessment(
    payload: AssessmentCreateRequest,
    service: AssessmentService = Depends(get_assessment_service),
    current_user: User = Depends(get_current_user),
):
    """Registers a new migration assessment, owned by the current user."""
    assessment = await service.create_assessment(payload, current_user.id)
    return success_envelope(_to_response(assessment), message="Assessment created successfully.")


@router.get("/assessments/{assessment_id}")
async def get_assessment(
    assessment_id: str,
    service: AssessmentService = Depends(get_assessment_service),
    current_user: User = Depends(get_current_user),
):
    """Fetches a single assessment's details. 404s if it does not exist or
    isn't owned by the current user."""
    assessment = await service.get_assessment(assessment_id, current_user.id)
    return success_envelope(_to_response(assessment), message="Assessment retrieved successfully.")


@router.patch("/assessments/{assessment_id}/status")
async def update_assessment_status(
    assessment_id: str,
    payload: AssessmentStatusUpdateRequest,
    service: AssessmentService = Depends(get_assessment_service),
    current_user: User = Depends(get_current_user),
):
    """Transitions an assessment's lifecycle status. 404s if it does not exist
    or isn't owned by the current user."""
    assessment = await service.update_status(assessment_id, payload.status, current_user.id)
    return success_envelope(_to_response(assessment), message="Assessment status updated successfully.")
