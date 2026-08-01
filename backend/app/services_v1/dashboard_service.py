"""Business logic for the Dashboard Summary module.

Reads exclusively from the durable relational store (via AssessmentRepository) -
this is the whole point of the persistence layer: unlike the legacy in-memory
graph fallback, these numbers survive a process restart.
"""

from __future__ import annotations

from typing import Optional

from app.repositories.assessment_repository import AssessmentRepository

# Status values that count as "finished" and are therefore excluded from
# active_assessments. "complete" is a success terminal state; "failed" is a
# failure terminal state - neither is still "active".
_COMPLETED_STATUS = "complete"
_FAILED_STATUS = "failed"


class DashboardService:
    def __init__(self, assessment_repo: AssessmentRepository):
        self.assessment_repo = assessment_repo

    async def get_summary(self, user_id: str) -> dict:
        total = await self.assessment_repo.count_total_for_user(user_id)
        completed = await self.assessment_repo.count_by_status_for_user(user_id, _COMPLETED_STATUS)
        failed = await self.assessment_repo.count_by_status_for_user(user_id, _FAILED_STATUS)
        active = total - completed - failed

        latest = await self.assessment_repo.get_latest_for_user(user_id)
        latest_assessment_id: Optional[str] = latest.id if latest is not None else None

        return {
            "total_assessments": total,
            "completed_assessments": completed,
            "active_assessments": active,
            "latest_assessment_id": latest_assessment_id,
        }
