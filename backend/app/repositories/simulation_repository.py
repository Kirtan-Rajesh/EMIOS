"""Data-access layer for the AssessmentSimulation entity (one row per assessment)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.simulation import AssessmentSimulation


class SimulationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_assessment(self, assessment_id: str) -> Optional[AssessmentSimulation]:
        result = await self.session.execute(
            select(AssessmentSimulation).where(AssessmentSimulation.assessment_id == assessment_id)
        )
        return result.scalar_one_or_none()

    async def upsert(self, assessment_id: str, values: Dict[str, Any]) -> AssessmentSimulation:
        """Creates or replaces the single simulation record for an assessment -
        rerunning a simulation is an update, not a new history entry."""
        existing = await self.get_by_assessment(assessment_id)
        if existing is None:
            simulation = AssessmentSimulation(assessment_id=assessment_id, **values)
            self.session.add(simulation)
            try:
                await self.session.commit()
            except IntegrityError:
                # Lost a race with a concurrent upsert for the same assessment_id
                # (unique constraint) - someone else's insert won first. Fall back
                # to updating their row instead of surfacing a raw 500.
                await self.session.rollback()
                existing = await self.get_by_assessment(assessment_id)
                for key, value in values.items():
                    setattr(existing, key, value)
                simulation = existing
                await self.session.commit()
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            simulation = existing
            await self.session.commit()
        await self.session.refresh(simulation)
        return simulation
