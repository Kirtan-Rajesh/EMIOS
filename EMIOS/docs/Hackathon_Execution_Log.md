# EMIOS Hackathon Execution Log

This is the handoff document for every contributor and coding assistant. Read
it before changing code, update it after every material change, and keep the
current demo path working at all times.

## North-star demo

In under four minutes, a pre-sales architect uploads a legacy-system inventory,
views its Enterprise Digital Twin, runs a migration-risk simulation, receives
sequenced migration waves, and exports an explainable executive recommendation.

**Demo customer:** ABC Insurance. **Narrative:** 32 applications, 7 databases,
126 APIs, 284 dependencies; readiness 78%; medium risk; high complexity; a
12-engineer team can complete the recommended staged migration in nine months.

## Current verified state — 2026-07-24

- Repository root: `C:\Users\kirtanr\Downloads\EMIOS\EMIOS` (there is no Git
  metadata in the supplied folder, so establish a remote repository before
  parallel feature work).
- Existing backend: FastAPI + Pydantic + NetworkX + LangGraph. It has an
  in-memory fallback when Neo4j/Qdrant are unavailable.
- Existing frontend: a static single-page UI served by FastAPI. It is not yet
  the requested TypeScript/Tailwind/shadcn application.
- Existing API capabilities: graph load/reset/upload, risk simulation,
  migration planning, health, observability, and a Copilot-style endpoint.
- Existing automated tests: API routes, simulation math, prompt rendering, and
  observability. `pytest.ini` and `backend/tests/conftest.py` were added so
  `python -m pytest` resolves backend imports without a manual `PYTHONPATH`.
- Test blocker observed: the system Python has FastAPI/pytest but is missing
  required libraries such as `networkx`. Install dependencies into one pinned
  Python 3.11 virtual environment before treating test status as a pass/fail
  quality signal.

## Architecture decision record

### Hackathon architecture (build this; do not over-engineer)

```text
Browser (React + TypeScript) --> FastAPI /api
                                  |
                             Assessment service
                                  |
                         Agent orchestrator (deterministic first)
                         /            |             \
                  Discovery       Risk/effort       Planner/report
                         \            |             /
                           Digital Twin contract
                                  |
                      In-memory demo store -> Neo4j (optional)
                                  |
                     Azure OpenAI only for explanation/synthesis
```

Rules:

1. Deterministic calculations own scores, waves, and estimates. An LLM may
   explain results but may not invent numeric outputs.
2. Keep an `Assessment` snapshot as the API boundary. Every screen reads the
   same immutable assessment ID, avoiding contradictory dashboard values.
3. The in-memory demo mode is the required demo path; Neo4j, Qdrant, Langfuse,
   and an LLM are progressive enhancements, never prerequisites.
4. Store API keys only in local environment variables or AWS Secrets Manager;
   never in source, screenshots, sample data, or prompts.

## Data contract / tables

For the hackathon, use Pydantic models and JSON fixtures first. Persist only if
there is time. The future relational tables and key fields are:

| Table | Purpose | Required fields |
|---|---|---|
| `assessments` | One user assessment | id, customer_name, project_name, target_cloud, status, created_at |
| `assets` | App, DB, API, ETL, queue, external system | id, assessment_id, name, asset_type, runtime, criticality, annual_cost |
| `dependencies` | Directed relationships | id, assessment_id, source_asset_id, target_asset_id, type, criticality, evidence |
| `findings` | Evidence-backed AI/deterministic findings | id, assessment_id, category, severity, statement, evidence_refs, confidence |
| `migration_waves` | Planned sequences | id, assessment_id, wave_number, asset_ids, rationale, risk_score |
| `scenarios` | What-if options | id, assessment_id, strategy, duration_months, risk_score, cost_usd, confidence |
| `reports` | Generated artefacts | id, assessment_id, format, storage_key, version |

Use UUID IDs, UTC timestamps, enum values for status/severity/type, and a JSON
`evidence_refs` field. Do not put raw uploaded documents or secrets in graph
node properties.

## Scope and ownership for five people

| Owner | Must deliver | Integration contract |
|---|---|---|
| Lead architect | assessment contract, orchestration, integration, demo | approves API models and owns demo branch |
| Member 1 | upload/parser/technology detector | returns normalized `assets`, `dependencies`, warnings |
| Member 2 | twin + graph UI/data adapter | consumes `GraphData`; node click exposes evidence and risks |
| Member 3 | assessment engine | pure functions returning scores, estimates, waves, assumptions |
| Member 4 | dashboard, explanations, report UI | consumes one assessment snapshot; no score calculation in UI |

No contributor changes another owner’s contract without an issue and a short
review. Merge small, independently testable changes behind the demo fixture.

## Delivery order

1. **P0 — demo reliability:** pin a Python 3.11 environment, make all tests
   green, add a single `abc-insurance.json` fixture, and ensure offline demo
   mode works.
2. **P1 — assessment spine:** create/return one assessment payload; connect
   upload → normalized graph → deterministic scoring → waves.
3. **P2 — judge-facing UI:** assessment progress, twin/graph interactions,
   findings, three scenarios, explainability, and downloadable HTML/PDF report.
4. **P3 — cloud polish:** deploy the API/UI, add trace links, smoke-test the
   deployed app, rehearse the fallback path.

## Quality gates

- Unit: parsers, score formulas, cycle handling, wave ordering, report mapping.
- API integration: successful upload, invalid upload, assessment retrieval,
  simulation, planner, report and health routes.
- UI smoke: all demo screens render, file upload works, graph node opens,
  scenario selection updates insights, and report download succeeds.
- Demo regression: complete the four-minute script using only the fixture and
  no external LLM/database credentials.
- Security: no secrets in repository; uploads limited by type/size; validate
  filenames and return safe error messages.

## AWS budget — USD 70 hard cap

Use a lean serverless deployment: S3 + CloudFront for the frontend, Lambda +
API Gateway for FastAPI (or one small App Runner/ECS service only if Lambda
packaging costs time), DynamoDB on-demand for assessment metadata, and S3 for
reports. Keep Neo4j/Qdrant/Langfuse local or mocked for the hackathon.

| Bucket | Cap | Control |
|---|---:|---|
| Hosting/API/storage | $20 | Budget alert at $10/$15/$20; destroy after judging |
| Model calls | $25 | hard per-run token limit; cache fixture output; no background loops |
| Contingency | $25 | only spend after the full demo is deployed and tested |

Create an AWS Budget alert at $35 and $55, tag every resource `project=emios`
and `expires=hackathon-end`, and set a calendar reminder to delete resources.
Verify current service pricing in the AWS console before provisioning.

## Resume checklist

1. Read this file and `docs/Hackathon_Master_Prompts.md`.
2. Run `python -m pytest`; if imports fail, activate the shared Python 3.11
   virtual environment and install the core requirements.
3. Run the API in zero-configuration mode and execute the demo fixture.
4. Check open P0 work and add a dated entry below before/after a change.

## Change log

| Date | Change | Validation | Owner |
|---|---|---|---|
| 2026-07-24 | Added test-path configuration and this resumable architecture/execution log. | Import-path configuration reviewed; dependency installation remains an environment blocker. | Codex |
