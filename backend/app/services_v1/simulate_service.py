"""Business logic for the Simulation Result module.

Unlike migration waves (which just store externally-computed planner output),
this module actually *runs* the simulation - reusing the existing
``app.services.simulation_engine`` cascading-failure/Monte Carlo engines, fed with
this assessment's own persisted graph (app/services_v1/graph_service.py), not the
legacy global in-memory/Neo4j graph. This keeps per-assessment simulation results
correctly scoped instead of silently depending on whatever graph happens to be
"active" globally.
"""

from __future__ import annotations

from typing import Any, Dict, List

from starlette.concurrency import run_in_threadpool

from app.core import constants
from app.core.exceptions import BadRequestException, ResourceNotFoundException
from app.entities.assessment import Assessment
from app.entities.simulation import AssessmentSimulation
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.simulation_repository import SimulationRepository
from app.services.simulation_engine import run_cascading_failure, run_monte_carlo
from app.services_v1.graph_service import to_dependency_edges, to_service_nodes


class SimulateService:
    def __init__(
        self,
        simulation_repo: SimulationRepository,
        graph_repo: GraphRepository,
        assessment_repo: AssessmentRepository,
    ):
        self.simulation_repo = simulation_repo
        self.graph_repo = graph_repo
        self.assessment_repo = assessment_repo

    async def _require_assessment(self, assessment_id: str) -> Assessment:
        assessment = await self.assessment_repo.get_by_id(assessment_id)
        if assessment is None:
            raise ResourceNotFoundException(f"Assessment '{assessment_id}' was not found.")
        return assessment

    async def _require_graph(self, assessment_id: str):
        nodes, edges = await self.graph_repo.get_graph(assessment_id)
        if not nodes:
            raise BadRequestException(
                f"No graph has been posted for assessment '{assessment_id}' yet. "
                f"POST /api/v1/assessments/{assessment_id}/graph before running a simulation."
            )
        return to_service_nodes(nodes), to_dependency_edges(edges)

    async def run_simulation(self, assessment_id: str, target_id: str, already_migrated: List[str]) -> Dict[str, Any]:
        await self._require_assessment(assessment_id)
        nodes, edges = await self._require_graph(assessment_id)

        if not any(n.id == target_id for n in nodes):
            raise BadRequestException(
                f"Target service '{target_id}' was not found in assessment '{assessment_id}''s graph."
            )

        # run_cascading_failure/run_monte_carlo are synchronous and CPU-bound
        # (the latter defaults to settings.MAX_SIMULATION_RUNS iterations over
        # every node) - offload to the threadpool so one simulation doesn't
        # stall the event loop for every other concurrent request, matching
        # the run_in_threadpool pattern used by every other v1 service.
        impacted_nodes, critical_paths, revenue_at_risk = await run_in_threadpool(
            run_cascading_failure, nodes=nodes, edges=edges, target_id=target_id, already_migrated=already_migrated
        )
        monte_carlo_res = await run_in_threadpool(run_monte_carlo, nodes, impacted_nodes)

        total_hosting_cost = round(sum(n.annual_cost for n in nodes), 2)
        potential_savings = round(total_hosting_cost * constants.CLOUD_SAVINGS_MULTIPLIER, 2)

        values = {
            "target_id": target_id,
            "already_migrated": list(already_migrated),
            "impacted_services": [n.model_dump(mode="json") for n in impacted_nodes],
            "critical_paths": critical_paths,
            "monte_carlo": monte_carlo_res.model_dump(mode="json"),
            "revenue_at_risk": revenue_at_risk,
            "total_hosting_cost": total_hosting_cost,
            "potential_savings": potential_savings,
        }
        simulation = await self.simulation_repo.upsert(assessment_id, values)
        return self._to_result_dict(assessment_id, simulation)

    async def get_simulation(self, assessment_id: str) -> Dict[str, Any]:
        await self._require_assessment(assessment_id)
        simulation = await self.simulation_repo.get_by_assessment(assessment_id)
        if simulation is None:
            raise ResourceNotFoundException(f"No simulation has been run yet for assessment '{assessment_id}'.")
        return self._to_result_dict(assessment_id, simulation)

    def _to_result_dict(self, assessment_id: str, simulation: AssessmentSimulation) -> Dict[str, Any]:
        return {
            "assessment_id": assessment_id,
            "target_id": simulation.target_id,
            "impacted_services": simulation.impacted_services,
            "critical_paths": simulation.critical_paths,
            "revenue_at_risk": simulation.revenue_at_risk,
            "total_hosting_cost": simulation.total_hosting_cost,
            "potential_savings": simulation.potential_savings,
            "monte_carlo": simulation.monte_carlo,
        }
