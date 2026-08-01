"""Business logic for the Assessment Graph Persistence module.

Known architecture constraint (handled explicitly here, not papered over):
``app.services.neo4j_service`` maintains a single GLOBAL graph store (used by the
legacy /api/graph, /api/simulate, /api/plan, etc.), not a multi-tenant one. Full
per-assessment Neo4j isolation is out of scope for this pass. Instead, after the
relational (per-assessment, source-of-truth) tables are written, we make a
best-effort call into ``reset_and_populate_graph`` to also push this assessment's
graph into the shared Neo4j store, so it becomes "the active graph" for the legacy
surface and the visualization it powers (last write wins across assessments). That
call is wrapped so a Neo4j failure never fails this request - matches the house
"degrade gracefully" style used throughout the codebase.
"""

from __future__ import annotations

import logging
from typing import List, Sequence, Tuple

from starlette.concurrency import run_in_threadpool

from app.core.exceptions import ResourceNotFoundException
from app.entities.assessment import Assessment
from app.entities.graph import AssessmentEdge, AssessmentNode
from app.models.schemas import DependencyEdge, GraphData, ServiceNode
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.graph_repository import GraphRepository

logger = logging.getLogger("emios")

# Baseline per-node migration risk, computed from topology alone (no LLM, no
# simulation run) so every persisted graph node carries a genuine, non-zero
# risk figure the moment it exists - not just during a one-off What-If
# Simulation targeting that specific node. Before this, ServiceNode.
# failure_probability defaulted to 0.0 and nothing at graph-persist time ever
# set it to anything else: simulation_engine.py computes real values, but only
# into a simulation run's own transient output (AssessmentSimulation row),
# never written back onto the graph's own AssessmentNode rows. That silently
# broke every "risk by service" view reading straight off the graph (GraphPage's
# node risk-tier coloring, OverviewPage's risk distribution chart) - both
# always saw 0.0 for every node, forever, regardless of real topology.
#
# Same weighting spirit as the cascading-failure engine's own criticality
# factors (app/core/constants.py's CRITICALITY_FACTOR_*) and the now-removed
# 4-agent Risk Agent's violation scoring: migration_complexity sets an
# inherent baseline, then a node picks up more risk for each high/medium
# criticality dependent that could be broken by its migration, and for each
# tightly-coupled (Sync, High-criticality) call it itself makes outward.
_COMPLEXITY_BASE_RISK = {"High": 0.35, "Medium": 0.20, "Low": 0.08}
_INCOMING_CRITICALITY_RISK = {"High": 0.08, "Medium": 0.04, "Low": 0.0}
_OUTGOING_TIGHT_COUPLING_RISK = 0.05


def _compute_baseline_risk(node: ServiceNode, edges: List[DependencyEdge]) -> float:
    score = _COMPLEXITY_BASE_RISK.get(node.migration_complexity, 0.20)
    for e in edges:
        if e.target == node.id:
            score += _INCOMING_CRITICALITY_RISK.get(e.criticality, 0.0)
        elif e.source == node.id and e.type == "Sync" and e.criticality == "High":
            score += _OUTGOING_TIGHT_COUPLING_RISK
    return round(min(score, 1.0), 2)


def to_service_nodes(nodes: Sequence[AssessmentNode]) -> List[ServiceNode]:
    return [
        ServiceNode(
            id=n.node_id,
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
        for n in nodes
    ]


def to_dependency_edges(edges: Sequence[AssessmentEdge]) -> List[DependencyEdge]:
    return [
        DependencyEdge(
            source=e.source,
            target=e.target,
            type=e.type,
            criticality=e.criticality,
            is_discovered=e.is_discovered,
        )
        for e in edges
    ]


class GraphService:
    def __init__(self, graph_repo: GraphRepository, assessment_repo: AssessmentRepository):
        self.graph_repo = graph_repo
        self.assessment_repo = assessment_repo

    async def _require_assessment(self, assessment_id: str) -> Assessment:
        assessment = await self.assessment_repo.get_by_id(assessment_id)
        if assessment is None:
            raise ResourceNotFoundException(f"Assessment '{assessment_id}' was not found.")
        return assessment

    async def persist_graph(self, assessment_id: str, payload: GraphData) -> dict:
        await self._require_assessment(assessment_id)

        nodes_with_risk = [
            n.model_copy(update={"failure_probability": _compute_baseline_risk(n, payload.edges)})
            for n in payload.nodes
        ]
        await self.graph_repo.replace_graph(assessment_id, nodes_with_risk, payload.edges)

        graph_status = "persisted"
        try:
            # Best-effort sync into the shared Neo4j store - see module docstring.
            # reset_and_populate_graph is synchronous and makes one blocking Neo4j
            # session.run() call per node/edge - offload to the threadpool so it
            # doesn't stall the event loop for every other concurrent request,
            # matching the run_in_threadpool pattern used by every other v1 service.
            from app.services.neo4j_service import reset_and_populate_graph

            await run_in_threadpool(
                reset_and_populate_graph,
                [n.model_dump() for n in nodes_with_risk],
                [e.model_dump() for e in payload.edges],
            )
            graph_status = "persisted_and_synced_to_neo4j"
        except Exception as ex:
            logger.warning(f"Best-effort Neo4j sync failed for assessment '{assessment_id}': {ex}")
            graph_status = "persisted_neo4j_sync_failed"

        return {
            "assessment_id": assessment_id,
            "node_count": len(payload.nodes),
            "edge_count": len(payload.edges),
            "graph_status": graph_status,
        }

    async def get_graph(self, assessment_id: str) -> Tuple[str, List[ServiceNode], List[DependencyEdge]]:
        await self._require_assessment(assessment_id)
        nodes, edges = await self.graph_repo.get_graph(assessment_id)
        return assessment_id, to_service_nodes(nodes), to_dependency_edges(edges)
