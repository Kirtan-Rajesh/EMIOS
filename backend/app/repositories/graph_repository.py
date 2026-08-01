"""Data-access layer for the per-assessment persisted graph (AssessmentNode/AssessmentEdge)."""

from __future__ import annotations

from typing import List, Sequence, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.graph import AssessmentEdge, AssessmentNode
from app.models.schemas import DependencyEdge, ServiceNode


class GraphRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def replace_graph(
        self, assessment_id: str, nodes: List[ServiceNode], edges: List[DependencyEdge]
    ) -> None:
        """Full replace: POSTing a graph for an assessment overwrites whatever was
        persisted for it before (there is no versioned history of assessment graphs)."""
        await self.session.execute(delete(AssessmentEdge).where(AssessmentEdge.assessment_id == assessment_id))
        await self.session.execute(delete(AssessmentNode).where(AssessmentNode.assessment_id == assessment_id))

        for n in nodes:
            self.session.add(
                AssessmentNode(
                    assessment_id=assessment_id,
                    node_id=n.id,
                    name=n.name,
                    type=n.type,
                    business_value=n.business_value,
                    revenue_impact=n.revenue_impact,
                    migration_complexity=n.migration_complexity,
                    base_cost=n.base_cost,
                    base_duration=n.base_duration,
                    status=n.status,
                    failure_probability=n.failure_probability,
                    runtime=n.runtime,
                    annual_cost=n.annual_cost,
                )
            )
        for e in edges:
            self.session.add(
                AssessmentEdge(
                    assessment_id=assessment_id,
                    source=e.source,
                    target=e.target,
                    type=e.type,
                    criticality=e.criticality,
                    is_discovered=e.is_discovered,
                )
            )
        await self.session.commit()

    async def get_graph(self, assessment_id: str) -> Tuple[Sequence[AssessmentNode], Sequence[AssessmentEdge]]:
        node_result = await self.session.execute(
            select(AssessmentNode).where(AssessmentNode.assessment_id == assessment_id)
        )
        edge_result = await self.session.execute(
            select(AssessmentEdge).where(AssessmentEdge.assessment_id == assessment_id)
        )
        return node_result.scalars().all(), edge_result.scalars().all()
