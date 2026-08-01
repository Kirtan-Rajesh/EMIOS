"""Data-access layer for the Assessment entity. No business rules live here -
just persistence operations against the async SQLAlchemy session."""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.assessment import Assessment


class AssessmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, assessment: Assessment) -> Assessment:
        self.session.add(assessment)
        await self.session.commit()
        await self.session.refresh(assessment)
        return assessment

    async def get_by_id(self, assessment_id: str) -> Optional[Assessment]:
        """Unscoped lookup - used internally by sub-resource services (graph,
        uploads, simulate, ...) that only need to confirm the assessment
        exists, not enforce ownership. Ownership is enforced at the
        Assessment Lifecycle routes themselves via get_by_id_for_user."""
        result = await self.session.execute(select(Assessment).where(Assessment.id == assessment_id))
        return result.scalar_one_or_none()

    async def get_by_id_for_user(self, assessment_id: str, user_id: str) -> Optional[Assessment]:
        result = await self.session.execute(
            select(Assessment).where(Assessment.id == assessment_id, Assessment.created_by == user_id)
        )
        return result.scalar_one_or_none()

    async def update_status(self, assessment: Assessment, status: str) -> Assessment:
        assessment.status = status
        await self.session.commit()
        await self.session.refresh(assessment)
        return assessment

    async def list_for_user(self, user_id: str) -> Sequence[Assessment]:
        result = await self.session.execute(select(Assessment).where(Assessment.created_by == user_id))
        return result.scalars().all()

    async def count_total_for_user(self, user_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Assessment).where(Assessment.created_by == user_id)
        )
        return int(result.scalar_one())

    async def count_by_status_for_user(self, user_id: str, status: str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Assessment)
            .where(Assessment.created_by == user_id, Assessment.status == status)
        )
        return int(result.scalar_one())

    async def get_latest_for_user(self, user_id: str) -> Optional[Assessment]:
        result = await self.session.execute(
            select(Assessment)
            .where(Assessment.created_by == user_id)
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
            .limit(1)
        )
        return result.scalars().first()
