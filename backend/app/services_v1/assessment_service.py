"""Business logic for the Assessment Lifecycle module."""

from __future__ import annotations

from typing import Sequence

from app.core import observability
from app.core.exceptions import ResourceNotFoundException
from app.entities.assessment import Assessment
from app.repositories.assessment_repository import AssessmentRepository
from app.schemas_v1.assessment import AssessmentCreateRequest


class AssessmentService:
    def __init__(self, assessment_repo: AssessmentRepository):
        self.assessment_repo = assessment_repo

    async def list_assessments(self, user_id: str) -> Sequence[Assessment]:
        # Newest first - matches AssessmentRepository.get_latest_for_user()'s
        # ordering convention so "most recent" means the same thing across
        # the dashboard and this list.
        assessments = await self.assessment_repo.list_for_user(user_id)
        return sorted(assessments, key=lambda a: (a.created_at, a.id), reverse=True)

    async def create_assessment(self, payload: AssessmentCreateRequest, user_id: str) -> Assessment:
        assessment = Assessment(
            customer_name=payload.customer_name,
            project_name=payload.project_name,
            target_cloud=payload.target_cloud,
            status=payload.status,
            created_by=user_id,
        )
        created = await self.assessment_repo.create(assessment)
        # Seeds this assessment's single Langfuse trace + its "User Input" sub-trace
        # (see app.core.observability.record_assessment_created) - every later agent/
        # report LLM call for this assessment_id nests under the same trace.
        observability.record_assessment_created(
            created.id, created.customer_name, created.project_name, created.target_cloud
        )
        return created

    async def get_assessment(self, assessment_id: str, user_id: str) -> Assessment:
        assessment = await self.assessment_repo.get_by_id_for_user(assessment_id, user_id)
        if assessment is None:
            raise ResourceNotFoundException(f"Assessment '{assessment_id}' was not found.")
        return assessment

    async def update_status(self, assessment_id: str, status: str, user_id: str) -> Assessment:
        assessment = await self.get_assessment(assessment_id, user_id)
        return await self.assessment_repo.update_status(assessment, status)
