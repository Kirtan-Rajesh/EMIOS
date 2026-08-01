"""Business logic for the Agent Run / Observability module.

``run_planner()`` (the plain, non-streaming path - currently unused by the
frontend, which always streams) still runs the original 4-agent Discovery/
Dependency/Planner/Risk negotiation loop (``app.agents.workflow.run_agent_negotiation`` -
the same engine behind the legacy ``POST /api/plan``).

``run_planner_stream()`` instead runs the full 12-agent Master Orchestrator
pipeline (``app.agents.workflow.run_full_assessment_stream``, the engine
behind the legacy ``POST /api/assess``) so the one live frontend path
(PlannerPage/PlannerRunPanel) exercises the whole pipeline instead of just the
4-agent subset - this closes the "Agent Architecture Split" gap where the
12-agent pipeline only ever ran in-memory on `/api/assess`, disconnected from
the persisted, database-backed `/api/v1` assessment flow. Two behavioral
differences from before: there's no Planner<->Risk revision loop (the 12-agent
pipeline's Migration Planner Agent runs once, unconditionally), and its risk
step is Risk Assessment Agent (8-category enterprise risk), not the 4-agent
loop's Risk Agent (per-service risk/objections) - see
run_full_assessment_stream()'s docstring for the full detail.

Each row records one ``AgentRun`` row per negotiation-log entry produced.
This gives per-assessment observability into what each agent did instead of
the legacy surface's ephemeral, global-graph-only planning result.

Every row from one negotiation is tagged with a shared ``batch_id``, and the
terminal row also carries the negotiation's authoritative computed output
(``AgentRun.final_result``) - see that field's docstring - so
``get_latest_result()`` can reconstruct the exact same response shape a fresh
run returns, without re-running anything, for a caller that just wants to see
the last completed run (e.g. the Planner page on mount, or a "View" action
after a background auto-run finishes).

For the 12-agent pipeline (``run_planner_stream``), the terminal row also
carries ``AgentRun.pipeline_metrics`` - the extra computed state (complexity
scores, enterprise risk breakdown, cloud readiness/platform scores,
simulation scenarios, recommendation, explainability) that the pipeline
produces beyond waves/decoupling_strategies/risk_assessment. See
``PIPELINE_METRICS_KEYS`` below for the exact key set.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Sequence, Tuple

from starlette.concurrency import run_in_threadpool

from app.agents.workflow import run_agent_negotiation, run_full_assessment_stream
from app.core.exceptions import BadRequestException, ResourceNotFoundException
from app.entities.agent_run import AgentRun
from app.entities.assessment import Assessment
from app.repositories.agent_run_repository import AgentRunRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.graph_repository import GraphRepository
from app.services_v1.graph_service import to_dependency_edges, to_service_nodes

# Extra 12-agent-pipeline state carried on the terminal AgentRun row's
# pipeline_metrics column (see that field's docstring) - kept as a single
# tuple so run_planner_stream()'s "complete" event and get_latest_result()'s
# reconstruction can't drift apart on which keys count as "pipeline metrics".
PIPELINE_METRICS_KEYS = (
    "complexity",
    "enterprise_risk",
    "cloud_readiness",
    "simulation_results",
    "recommendation",
    "explainability",
    "confidence_score",
)


class AgentRunService:
    def __init__(
        self,
        agent_run_repo: AgentRunRepository,
        graph_repo: GraphRepository,
        assessment_repo: AssessmentRepository,
    ):
        self.agent_run_repo = agent_run_repo
        self.graph_repo = graph_repo
        self.assessment_repo = assessment_repo

    async def _require_assessment(self, assessment_id: str) -> Assessment:
        assessment = await self.assessment_repo.get_by_id(assessment_id)
        if assessment is None:
            raise ResourceNotFoundException(f"Assessment '{assessment_id}' was not found.")
        return assessment

    async def _load_graph_for_negotiation(self, assessment_id: str) -> Tuple[List[dict], List[dict]]:
        await self._require_assessment(assessment_id)
        nodes, edges = await self.graph_repo.get_graph(assessment_id)
        if not nodes:
            raise BadRequestException(
                f"No graph has been posted for assessment '{assessment_id}' yet. "
                f"POST /api/v1/assessments/{assessment_id}/graph before running the planner."
            )
        service_nodes = to_service_nodes(nodes)
        dependency_edges = to_dependency_edges(edges)
        return [n.model_dump() for n in service_nodes], [e.model_dump() for e in dependency_edges]

    async def ensure_ready_for_planner(self, assessment_id: str) -> None:
        """Raises ResourceNotFoundException/BadRequestException if the planner
        can't proceed for this assessment. Called eagerly by the streaming
        route (so a bad assessment_id/no-graph case still gets a normal
        404/400 instead of a 200 stream that immediately errors) - the same
        checks run_planner_stream() does internally, exposed separately so
        the endpoint can await them before the StreamingResponse commits."""
        await self._load_graph_for_negotiation(assessment_id)

    async def run_planner(self, assessment_id: str) -> Dict[str, Any]:
        services, dependencies = await self._load_graph_for_negotiation(assessment_id)

        # run_agent_negotiation() is synchronous and makes several sequential blocking
        # LLM calls - offload to the threadpool so one assessment's agent run doesn't
        # freeze the event loop (and every other request) for its full duration.
        negotiation_res = await run_in_threadpool(
            run_agent_negotiation, services, dependencies, assessment_id=assessment_id
        )

        batch_id = uuid.uuid4().hex
        final_result = {
            "waves": negotiation_res.get("proposed_waves", []),
            "decoupling_strategies": negotiation_res.get("decoupling_strategies", []),
            "risk_assessment": negotiation_res.get("risk_assessment", {}),
        }

        # All stages already ran to completion by the time run_agent_negotiation()
        # returns (it's synchronous), so started_at/completed_at are recorded
        # identically and post-hoc rather than tracking real wall-clock duration.
        recorded_at = datetime.now(timezone.utc)
        logs = negotiation_res.get("negotiation_logs", [])
        runs: List[AgentRun] = []
        for i, log in enumerate(logs):
            run = await self.agent_run_repo.create(
                AgentRun(
                    assessment_id=assessment_id,
                    agent_name=log.get("agent", "Unknown Agent"),
                    status="completed",
                    started_at=recorded_at,
                    completed_at=recorded_at,
                    summary=log,
                    batch_id=batch_id,
                )
            )
            runs.append(run)
        if runs:
            await self.agent_run_repo.set_final_result(runs[-1], final_result)

        return {
            "assessment_id": assessment_id,
            **final_result,
            "agent_runs": [self._to_dict(r) for r in runs],
        }

    async def run_planner_stream(self, assessment_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming twin of run_planner() in event shape only - it actually
        runs the full 12-agent Master Orchestrator pipeline
        (run_full_assessment_stream), not run_planner()'s 4-agent negotiation
        loop; see this module's docstring for why. Yields one event per
        completed agent stage as it happens (each persisted immediately, so
        the result is durable even if the client disconnects mid-stream),
        then a final `{"type": "complete", ...}` event."""
        services, dependencies = await self._load_graph_for_negotiation(assessment_id)

        yield {"type": "start", "assessment_id": assessment_id}

        batch_id = uuid.uuid4().hex
        sync_gen = run_full_assessment_stream(services, dependencies, assessment_id=assessment_id)

        sentinel = object()
        final_result: Optional[Dict[str, Any]] = None
        pipeline_metrics: Optional[Dict[str, Any]] = None
        last_run: Optional[AgentRun] = None
        try:
            while True:
                # Each next() call blocks on a synchronous LLM call inside the
                # generator - offload every step to the threadpool so this
                # doesn't stall the event loop between yields, matching the
                # per-document offload pattern in discovery_service.py.
                item = await run_in_threadpool(next, sync_gen, sentinel)
                if item is sentinel:
                    break

                if item.get("type") == "complete":
                    # Carries every structured field the 12-agent pipeline computed, not
                    # just the 4-agent loop's original three - see
                    # run_full_assessment_stream()'s docstring. app/services_v1/
                    # report_service.py reads this back to build a report without
                    # re-running the pipeline.
                    final_result = {k: v for k, v in item.items() if k != "type"}
                    pipeline_metrics = {key: item.get(key) for key in PIPELINE_METRICS_KEYS}
                    continue

                recorded_at = datetime.now(timezone.utc)
                last_run = await self.agent_run_repo.create(
                    AgentRun(
                        assessment_id=assessment_id,
                        agent_name=item.get("agent", "Unknown Agent"),
                        status="completed",
                        started_at=recorded_at,
                        completed_at=recorded_at,
                        summary=item,
                        batch_id=batch_id,
                    )
                )
                yield {"type": "agent_result", **self._to_dict(last_run)}
        except Exception as ex:
            yield {"type": "error", "message": str(ex)}
            return

        if final_result is None or last_run is None:
            yield {"type": "error", "message": "Agent negotiation ended without a final result."}
            return

        await self.agent_run_repo.set_final_result(last_run, final_result, pipeline_metrics)

        yield {
            "type": "complete",
            "assessment_id": assessment_id,
            **final_result,
            **(pipeline_metrics or {}),
        }

    async def get_latest_result(self, assessment_id: str) -> Optional[Dict[str, Any]]:
        """Reconstructs the last completed run_planner()/run_planner_stream()
        result from persisted AgentRun rows, without re-running anything -
        None if the planner has never successfully completed for this
        assessment (a caller should treat that as "nothing to show yet",
        prompting a fresh run rather than an error)."""
        await self._require_assessment(assessment_id)
        rows = await self.agent_run_repo.get_latest_batch(assessment_id)
        if not rows:
            return None

        terminal_row = next((r for r in reversed(rows) if r.final_result), None)
        if terminal_row is None:
            # A batch exists but never reached a terminal row (e.g. the process
            # was killed mid-negotiation) - nothing authoritative to show.
            return None

        final_result = terminal_row.final_result
        pipeline_metrics = terminal_row.pipeline_metrics or {}
        return {
            "assessment_id": assessment_id,
            **final_result,
            **{key: pipeline_metrics.get(key) for key in PIPELINE_METRICS_KEYS},
            "agent_runs": [self._to_dict(r) for r in rows],
        }

    async def list_agent_runs(self, assessment_id: str) -> Sequence[AgentRun]:
        await self._require_assessment(assessment_id)
        return await self.agent_run_repo.list_for_assessment(assessment_id)

    @staticmethod
    def _to_dict(run: AgentRun) -> Dict[str, Any]:
        return {
            "agent_run_id": run.id,
            "assessment_id": run.assessment_id,
            "agent_name": run.agent_name,
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "summary": run.summary,
        }
