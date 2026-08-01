# EMIOS Master Agent Orchestrator — Implementation Notes

Documents the full 12-agent pipeline added on top of the existing 4-node LangGraph
negotiation loop. Read this alongside the repo root `README.md` (architecture map,
setup, conventions) — this file only covers the orchestrator subsystem.

## What existed before this work

`app/agents/workflow.py` already had a working LangGraph state machine:

```
discovery_agent -> dependency_agent -> planner_agent -> risk_agent -> (loop back to planner_agent until satisfied)
```

wired into `run_agent_negotiation()`, used by the legacy `POST /api/plan` endpoint.
**This loop is untouched** — its return shape is depended on by `test_api.py` and the
existing frontend flow.

## What was added: `run_full_assessment()`

A second, separate LangGraph pipeline implementing the full Master Orchestrator spec
(12 agents, shared `AssessmentState`, conditional routing). Exposed via a new endpoint:

```
POST /api/assess
```

which runs the pipeline against whatever graph is currently loaded (same pattern as
`/api/plan`: `get_graph()` → convert to dicts → orchestrate → wrap response).

### Pipeline graph

```
START
  │
  ▼
initialize_state          (seeds AssessmentState defaults)
  │
  ▼
discovery_agent            ── retries once if no runtimes/technologies detected
  │
  ▼
dependency_agent            ── retries once if dependency graph is empty
  │
  ▼
digital_twin_agent          (React Flow nodes/edges + Neo4j entity summary)
  │
  ▼
migration_graph_agent       (applications/DBs/queues/externals + decoupling strategies)
  │
  ▼
complexity_agent            (5-dimension complexity score, effort/timeline/team size)
  │
  ▼
enterprise_risk_agent       ("Risk Assessment Agent" — 8 risk categories, portfolio score)
  │
  ├── risk_score > 0.80 ──► simulation_agent (early pass) ──┐
  │                                                          │
  └──────────────────────────────────────────────────────────▶ cloud_readiness_agent
                                                               │
                                                               ▼
                                                      planner_agent (reused as-is)
                                                               │
                                                               ▼
                                                  simulation_agent (always runs again)
                                                               │
                                                               ▼
                                              recommendation_agent ── retries once if confidence < 85%
                                                               │
                                                               ▼
                                                    explainability_agent
                                                               │
                                                               ▼
                                                       report_agent
                                                               │
                                                               ▼
                                                              END
```

`simulation_agent` is registered as **two node ids** (`simulation_early` and
`simulation`) both wrapping the same function — Risk Assessment can route into the
early pass when risk is high; Migration Planner always routes into the later pass.
Either path reconverges before Recommendation.

Any node failing twice (exception, not business-logic disagreement) sets
`workflow_status = "HUMAN_REVIEW_REQUIRED"` and short-circuits straight to `END`.

## Files changed

| File | What changed |
|---|---|
| `app/agents/state.py` | `AgentState` extended (additive) with `digital_twin`, `migration_graph`, `complexity`, `enterprise_risk`, `cloud_readiness`, `simulation_results`, `recommendation`, `explainability`, `report`, `execution_history`, `current_agent`, `next_agent`, `confidence_score`, `retry_counts`, `workflow_status`, `status_reason`. |
| `app/agents/prompts.py` | 9 new prompt pairs (system + user), same strict-JSON-contract style as the existing 4: Digital Twin, Migration Graph, Complexity, Enterprise Risk, Cloud Readiness, Simulation, Recommendation, Explainability, Report. |
| `app/agents/workflow.py` | 9 new agent node functions + orchestrator plumbing (`_wrap_node`, routers, `run_full_assessment`). See below. |
| `app/core/constants.py` | New named thresholds/weights (complexity dimension weights, cloud readiness weights, per-strategy simulation multipliers, risk/readiness/confidence thresholds, `AGENT_MAX_RETRIES`). |
| `app/models/schemas.py` | `AgentStepResult` (per-step envelope) and `AssessmentReport` (final completion envelope) — the two JSON shapes from the spec. |
| `app/api/endpoints.py` | New `POST /api/assess` route. |
| `tests/test_full_assessment.py` | New test file: unit tests on individual nodes, router-branching tests, an end-to-end run on the demo dataset, a `HUMAN_REVIEW_REQUIRED` escalation test, and an API integration test. |

## Agent responsibilities and outputs

| Agent (node function) | Reuses | Produces |
|---|---|---|
| `initialize_state_node` | — | Seeds all bookkeeping fields (`workflow_status="RUNNING"`, empty result dicts, etc.) |
| `discovery_agent` | Existing, unmodified | Orphan detection, shared-DB detection (from the original 4-node loop) |
| `dependency_agent` | Existing, unmodified | Cycle detection + decoupling strategies (from the original 4-node loop) |
| `digital_twin_agent` | New | React Flow `nodes`/`edges`, node-type breakdown |
| `migration_graph_agent` | New | Applications/databases/queues-ETL/external-systems entity graph + decoupling strategies |
| `complexity_agent` | New | Architecture/Business/Technology/Integration/Migration dimension scores, `engineering_effort_days`, `estimated_timeline_weeks`, `team_size` |
| `enterprise_risk_agent` | New — distinct from the wave-sequencing `risk_agent` | 8-category risk score (technical/business/compliance/security/operational/performance/legacy/data_migration), top risks, mitigations |
| `cloud_readiness_agent` | New | Azure/AWS/GoogleCloud readiness scores + recommended platform (from runtime-keyword matching) |
| `simulation_agent` | Reuses `simulation_engine.run_monte_carlo` | Lift & Shift / Replatform / Refactor comparison (risk, duration, cost, effort, business impact, confidence per scenario) |
| `planner_agent` | Existing, unmodified | Topological migration waves |
| `recommendation_agent` | New | Recommended strategy + engineering/business/modernization/customer recommendations + confidence score |
| `explainability_agent` | New | Cites only prior agents' evidence — no new computation |
| `report_agent` | New | Final executive report JSON; `pdf`/`docx` marked `not_implemented` (no rendering library in `requirements.txt`) |

### Why `enterprise_risk_agent` is separate from `risk_agent`

The spec's pipeline places Risk Assessment *before* Migration Planner. The existing
`risk_agent` (used by `run_agent_negotiation`) evaluates wave-*sequencing* risk and
requires `proposed_waves` to already exist — it can't run before planning. So the new
pipeline uses a distinct, portfolio-level `enterprise_risk_agent` (stored in
`state["enterprise_risk"]`, not `state["risk_assessment"]`) that scores real topology
attributes directly, with no dependency on wave placement.

## Conditional routing implemented

| Spec rule | Implementation |
|---|---|
| Discovery can't identify technologies → retry once | **Removed 2026-07-31.** `_route_after_discovery` used to loop back to `discovery` once if no non-"Unknown" runtimes were found - but that check is a deterministic function of the unchanged `services` input, so a retry against the same input always got the same answer. Document-extracted systems routinely lack an explicit runtime, so this doubled Discovery Agent's LLM latency on effectively every real run for zero chance of a different outcome. Now a plain linear edge to `dependency`, same as every non-retrying node. |
| Dependencies incomplete → retry once | **Removed 2026-07-31**, same reasoning - `_route_after_dependency` looped back to `dependency` once if the dependency list was empty despite multiple services, which a same-input retry can't fix either. Now a plain linear edge to `digital_twin_node`. |
| Risk score > 80% → run all migration strategies | **Simplified 2026-07-31.** Used to branch into an early `simulation_early` pass via `_route_after_risk` - removed because it ran before Cloud Readiness had computed anything (so its `cloud_readiness` figures were always the zero default) and its entire output was unconditionally overwritten by the later, unconditional post-Planner Simulation Agent pass anyway. `simulation_agent` always evaluates all 3 strategies every run regardless, and still correctly sets `force_all_strategies: true` from `enterprise_risk` (populated by then) on its one remaining pass - nothing was lost. |
| Readiness < 60% → recommend modernization first | `recommendation_agent` prepends a `modernization_recommendation` when `cloud_readiness.readiness_score < 0.60` |
| Confidence < 85% → rerun with historical context | **Removed** (see `recommendation_agent`'s docstring) - the same same-input-retry-can't-help issue as the two rows above, caught first. `recommendation_node` now runs exactly once. |
| Any agent fails twice → `HUMAN_REVIEW_REQUIRED` | `_wrap_node` retries any node once on exception; two failures sets `workflow_status="HUMAN_REVIEW_REQUIRED"` + `status_reason`, and every router checks this first, routing straight to `END` |

## A LangGraph gotcha hit during implementation

Node ids cannot collide with `AgentState` field names — LangGraph treats state fields
as "channels" and raises `ValueError: '<name>' is already being used as a state key`.
Node ids like `digital_twin`, `complexity`, `recommendation` etc. had to be suffixed
(`digital_twin_node`, `complexity_node`, `recommendation_node`, ...) to avoid colliding
with the state keys of the same name.

## Explicitly out of scope

- **No new DB persistence** (`agent_runs`, `assessment_reports` tables). This pipeline
  runs entirely in-memory against the current graph, same as `/api/plan` already does —
  avoids conflicting with any in-flight persistence-layer work elsewhere in the repo.
- **No real PDF/DOCX generation.** `requirements.txt` has no `reportlab`/`python-docx`.
  `report_agent`'s `download_formats.json.status == "available"` (the real data);
  `pdf`/`docx` are marked `"not_implemented"` rather than faked.

## Verification

```bash
PYTHONPATH=backend pytest backend/tests -q
```
51/51 passing (43 pre-existing + 8 new in `test_full_assessment.py`).

Manual check against the real demo dataset:
```bash
python backend/main.py
curl -X POST http://localhost:8000/api/assess
```
