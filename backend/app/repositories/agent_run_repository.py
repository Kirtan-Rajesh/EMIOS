"""Data-access layer for the AgentRun entity."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.agent_run import AgentRun


class AgentRunRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, run: AgentRun) -> AgentRun:
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def set_final_result(
        self,
        run: AgentRun,
        final_result: Dict[str, Any],
        pipeline_metrics: Optional[Dict[str, Any]] = None,
    ) -> AgentRun:
        """Attaches the negotiation's authoritative computed output (and, for
        the 12-agent pipeline, its extra computed metrics) to the terminal row
        of its batch - see AgentRun.final_result/pipeline_metrics docstrings."""
        run.final_result = final_result
        if pipeline_metrics is not None:
            run.pipeline_metrics = pipeline_metrics
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def list_for_assessment(self, assessment_id: str) -> Sequence[AgentRun]:
        result = await self.session.execute(
            select(AgentRun)
            .where(AgentRun.assessment_id == assessment_id)
            .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        )
        return result.scalars().all()

    async def get_latest_batch(self, assessment_id: str) -> Sequence[AgentRun]:
        """Returns every row from the most recent run_planner()/
        run_planner_stream() invocation (same batch_id), oldest stage first -
        used to reconstruct the last completed planner result (e.g. a user
        revisiting the Planner page without re-running it). Empty if no batch-
        tagged runs exist yet (including pre-batch_id legacy rows)."""
        latest_batch = await self.session.execute(
            select(AgentRun.batch_id)
            .where(AgentRun.assessment_id == assessment_id, AgentRun.batch_id.is_not(None))
            .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
        batch_id: Optional[str] = latest_batch.scalar_one_or_none()
        if batch_id is None:
            return []

        result = await self.session.execute(
            select(AgentRun)
            .where(AgentRun.assessment_id == assessment_id, AgentRun.batch_id == batch_id)
            .order_by(AgentRun.started_at.asc(), AgentRun.id.asc())
        )
        return result.scalars().all()
