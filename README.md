# EMIOS — Enterprise Migration Intelligence Operating System

EMIOS builds a live **digital twin** of a company's application landscape from its own
uploaded documents (BRDs, HLDs, architecture diagrams, CSV/XLSX inventories, OpenAPI specs,
schema exports — whatever exists), simulates cascading migration-failure risk and cost/time
through a Monte Carlo engine, and negotiates a wave-by-wave migration roadmap through a
12-agent LangGraph pipeline (Discovery → Dependency → Digital Twin → Migration Graph →
Complexity → Risk → Cloud Readiness → Planner → Simulation → Recommendation → Explainability
→ Report). An Executive Copilot chat answers questions grounded in that same graph and the
documents actually uploaded (RAG), and the whole thing is presented as a real product UI, not
a slide deck — light/dark theme, live streaming agent panels, Mermaid flowcharts, PDF export.

This README is the single source of truth for setting the project up and continuing work on
it — read it fully before writing code, and if you're pasting context into an AI coding
assistant (Claude, Kiro, Copilot, etc.), paste this whole file first. Section 6
("Conventions and gotchas") exists specifically because those things aren't obvious from
reading the code alone and have already caused real bugs.

---

## 1. Quick facts

| | |
|---|---|
| Backend | FastAPI + Python 3.11+, served on `:8000` (API + built frontend, same origin) |
| Frontend | Vite + React 19 + TypeScript + Tailwind v4, dev server on `:5173` (proxies `/api` to `:8000`) |
| Databases | Neo4j (digital twin graph), PostgreSQL (everything else), Qdrant (RAG vector search) — all three degrade gracefully to an in-memory/local fallback if unreachable |
| LLM | AWS Bedrock preferred (currently `qwen.qwen3-coder-next`, fully swappable via `.env`), with OpenAI/Gemini/Azure OpenAI as configured fallbacks, and a deterministic non-AI fallback if nothing is configured at all |
| Containers | Podman (team standard) or Docker — the compose files are engine-agnostic |
| Tests | 193 passing (`pytest`), no live infra required — runs against an in-memory SQLite engine |

---

## 2. What's actually in the app

- **Document Discovery**: upload BRDs/HLDs/inventories/OpenAPI specs/schema dumps (PDF, DOCX,
  PPTX, XLSX, CSV, JSON, TXT, MD, or a `.zip` of several) → LLM-assisted extraction of systems
  and their dependencies → auto-persisted digital twin graph. Runs in the background (survives
  navigating away), with live progress and a completion toast from anywhere in the app.
- **Digital Twin Graph**: an interactive, force-directed visualization (`@xyflow/react`) of
  every discovered system and dependency, color-coded by failure risk, with CSV export
  (`nodes.csv`/`edges.csv`).
- **What-If Simulation**: pick one service and see the cascading-failure blast radius, revenue
  at risk, and current hosting cost — a cheap, deterministic BFS + Monte Carlo model, not an
  LLM call.
- **Wave Planner**: the 12-agent Master Orchestrator pipeline (`app/agents/workflow.py`'s
  `run_full_assessment_stream`) — streamed live over SSE with a persistent side panel showing
  each agent's real-time output (bold/tables/bullet lists/Mermaid flowcharts, rendered
  deterministically from each agent's own computed data — see §6.14). Auto-starts the moment a
  graph is built; the app-root `PlannerRunProvider` means it keeps running (and notifies you on
  completion) no matter what page you navigate to.
- **Report**: an executive summary + readiness score + recommendations, auto-generated the
  moment the planner finishes (chained the same way planner auto-starts after discovery),
  downloadable as PDF, with a feedback loop (thumbs up/down + comment → AI revises just the
  affected section) and full version history.
- **Executive Copilot**: a chat widget grounded in the assessment's own uploaded documents (RAG
  retrieval via Qdrant) plus its digital twin/report/simulation data — not a generic chatbot.
- **Light/dark theme**: toggle in the account menu (click your email in the sidebar, above
  "Settings"); persisted, no flash on load.

---

## 3. Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI, Python 3.11+ (3.11.8/3.12 both tested), Uvicorn |
| Agent orchestration | LangGraph + LangChain |
| Graph algorithms | NetworkX |
| Graph / digital twin store | Neo4j (Bolt `:7687`, browser UI `:7474`) |
| Relational persistence | PostgreSQL via SQLAlchemy 2.0 async (`asyncpg`); portable to SQLite for tests/no-container local dev |
| Vector store (RAG) | Qdrant (`:6333` REST / `:6334` gRPC) — document-chunk embeddings, filtered per-assessment; in-memory fallback if unreachable |
| Object storage | Amazon S3 (`boto3`) for uploaded documents; local-disk fallback under `backend/storage_fallback/` if no AWS credentials |
| LLM + embeddings | AWS Bedrock preferred (`app/core/llm_provider.py`, `app/core/embeddings.py`) — Titan v2 for embeddings, `qwen.qwen3-coder-next` for text by default; Gemini/OpenAI/Azure OpenAI as configured fallbacks; deterministic (non-AI) fallback if nothing is configured |
| Observability | Langfuse (self-hosted or cloud) — traces + prompt management, optional |
| Frontend | Vite + React 19 + TypeScript + Tailwind v4 + Radix UI (`frontend/src/`), built to `frontend/dist` and served by FastAPI from the same origin/port |
| Frontend extras | `@xyflow/react` (graph canvas), `recharts` (charts), `mermaid` (agent-generated flowcharts), `react-markdown` + `remark-gfm`, `framer-motion` |
| Containers | Podman (team standard — Docker also works, compose files are engine-agnostic) |

---

## 4. Setup from scratch

You need, regardless of OS: **Git**, **Python 3.11+**, **Node.js 20+** (npm comes with it), and
**Podman or Docker** with a compose provider (`podman compose version` / `docker compose
version` should print something). None of the databases are strictly required to run the app —
see "No containers available?" below — but you'll get a much better demo with them.

If you're on a locked-down **VDI/corporate machine**: you usually don't need admin rights for
any of this (`pyenv`/`nvm`/user-scope installers all work), but corporate proxies commonly break
`pip`/`npm`/container registry pulls — see the VDI note at the end of this section if installs
hang or fail with TLS/connection errors.

### 4.1 Windows (PowerShell)

```powershell
# 1. Prerequisites (skip anything already installed)
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
winget install Git.Git
winget install RedHat.Podman          # or: winget install Docker.DockerDesktop

# New PowerShell window after installing, so PATH updates take effect.

# 2. Podman needs a Linux VM on Windows - one-time setup:
podman machine init
podman machine start

# 3. Clone and enter the repo
git clone <this-repo-url>
cd <repo>

# 4. Python virtual environment (kept at repo root, not backend/ - see project layout)
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 5. Frontend build - main.py refuses to start without frontend/dist present
cd frontend
npm install
npm run build
cd ..

# 6. Environment config
Copy-Item backend\.env.example backend\.env
notepad backend\.env    # fill in real values - see section 5 for what each one does

# 7. Start Neo4j + Postgres + Qdrant
podman compose up -d
# or: docker compose up -d

# 8. Run the backend (serves API + built frontend on :8000)
.\venv\Scripts\python.exe backend\main.py
```
Open `http://localhost:8000`. There's also `run_emios.bat` at the repo root — a one-click
launcher that auto-detects Docker vs Podman, brings the compose stack up, and starts the
backend; double-click it or run `.\run_emios.bat` once steps 1-6 above are done once.

**For frontend hot-reload while developing UI**, skip `npm run build` in step 5 and instead run
`npm run dev` inside `frontend/` in a second terminal (port `5173`, proxies `/api` to `:8000` —
see `frontend/vite.config.ts`). You still need the backend running in the first terminal.

### 4.2 macOS

```bash
# 1. Prerequisites (Homebrew: https://brew.sh if you don't have it)
brew install python@3.12 node git podman
# or: brew install --cask docker

# 2. Podman needs a Linux VM on macOS too:
podman machine init
podman machine start

# 3. Clone and enter the repo
git clone <this-repo-url>
cd <repo>

# 4. Python virtual environment
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r backend/requirements.txt

# 5. Frontend build
cd frontend && npm install && npm run build && cd ..

# 6. Environment config
cp backend/.env.example backend/.env
nano backend/.env    # or any editor - fill in real values, see section 5

# 7. Start Neo4j + Postgres + Qdrant
podman compose up -d
# or: docker compose up -d

# 8. Run the backend
venv/bin/python backend/main.py
```
Open `http://localhost:8000`. For frontend hot-reload, run `npm run dev` inside `frontend/` in
a second terminal instead of `npm run build`.

### 4.3 Linux (Ubuntu/Debian shown; adjust the package manager for your distro)

```bash
# 1. Prerequisites
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git podman
# Node 20+ via nodesource (Ubuntu's default apt repo is usually too old):
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
# podman-compose or the compose plugin, whichever your distro ships:
sudo apt install -y podman-compose || true

# On native Linux, podman talks to the host kernel directly - no VM/podman machine step
# needed (that's a macOS/Windows-only requirement).

# 2. Clone and enter the repo
git clone <this-repo-url>
cd <repo>

# 3. Python virtual environment
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r backend/requirements.txt

# 4. Frontend build
cd frontend && npm install && npm run build && cd ..

# 5. Environment config
cp backend/.env.example backend/.env
$EDITOR backend/.env   # fill in real values, see section 5

# 6. Start Neo4j + Postgres + Qdrant
podman compose up -d
# or: docker compose up -d

# 7. Run the backend
venv/bin/python backend/main.py
```
Open `http://localhost:8000`. Same `npm run dev` note as above for frontend hot-reload.

> **Podman version note** (relevant to both Linux desktop and any server/VM deploy): older
> Podman (3.4.4, e.g. Ubuntu 22.04's apt default) has no `compose` subcommand at all, and its
> CNI networking backend has broken support for compose-managed bridge networks. If `podman
> compose up -d` fails outright, either install a newer Podman (4.x+) or fall back to
> `docker-compose` driven against Podman's Docker-API-compatible socket — see
> `scripts/deploy/RUNBOOK.md` §6.3 for the exact commands; this bit us for real on a Lightsail
> deploy.

### 4.4 No containers available?

The app is designed to degrade gracefully — every piece of infra has a fallback:
- **No Neo4j**: the digital twin graph falls back to in-memory storage (lost on restart, fully
  functional for a demo).
- **No Postgres**: point `DATABASE_URL` in `backend/.env` at SQLite instead:
  ```
  DATABASE_URL=sqlite+aiosqlite:///./emios_dev.db
  ```
- **No Qdrant**: RAG search falls back to an in-memory vector store.
- **No AWS/OpenAI/Gemini credentials**: LLM calls fall back to deterministic, non-AI narrative
  text; embeddings fall back to a deterministic hash-based pseudo-embedder. Everything still
  runs and is fully testable end-to-end, it just isn't "real AI" until you configure a provider.

You can genuinely run the whole thing with **zero containers and zero API keys** — just Python
+ Node — for a code-review or UI-only session.

### 4.5 VDI / locked-down machine notes

- If `pip install` or `npm install` hang or fail with SSL/proxy errors, your org likely
  requires a corporate proxy or an internal package mirror — check for `HTTP_PROXY`/
  `HTTPS_PROXY` env vars your IT team expects you to set, or an internal PyPI/npm registry URL
  (`pip config set global.index-url ...` / `npm config set registry ...`).
- Podman/Docker Desktop usually need either admin rights or membership in a local
  `docker-users`/`podman` group depending on policy - if `podman machine start` fails with a
  permissions error, that's an IT-managed restriction, not a project bug; fall back to §4.4
  (SQLite + in-memory fallbacks, no containers) and keep working.
- Antivirus/EDR software scanning every file `npm install` writes (hundreds of thousands of
  small files in `node_modules/`) is the single most common cause of "install is taking
  forever" on corporate machines - excluding the repo's `node_modules/` and `venv/` from
  real-time scanning (if your policy allows it) helps a lot.
- Long Windows paths: `node_modules/` nesting can exceed the legacy 260-character path limit
  on some Windows configurations. If `npm install` fails with path-length errors, enable long
  paths (`git config --global core.longpaths true`, and on the OS side,
  `New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1` from an elevated prompt if you have one) or clone closer to a drive root (e.g. `C:\dev\emios` instead of a deeply nested profile path).

---

## 5. Environment variables (`backend/.env`)

Copy `backend/.env.example` to `backend/.env` and fill in real values. **Never put real
credentials in `.env.example`** — it's checked into git; only `.env` itself is gitignored.

| Variable | Required? | What it does |
|---|---|---|
| `PORT` | No (default `8000`) | Backend port |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | No | Digital twin graph store; falls back to in-memory if unreachable |
| `QDRANT_HOST` / `QDRANT_PORT` | No | RAG vector search; falls back to in-memory if unreachable |
| `DATABASE_URL` | No (has a Postgres default) | Relational persistence (assessments/uploads/waves/etc.) — point at SQLite for a container-free setup, see §4.4 |
| `JWT_SECRET_KEY` | **Yes for anything beyond a single-dev demo** | Signs auth tokens; the code has a public, source-controlled dev default — anyone who's read this repo can forge tokens against that default. Generate a real one: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` / `AZURE_OPENAI_*` | No | LLM/embedding fallbacks behind Bedrock |
| `AWS_REGION` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | No (recommended) | Bedrock (LLM + embeddings) + S3 (document storage). Leave the two credential vars blank on a real deployment and attach an IAM role instead — `app.core.config.get_boto3_client()` falls back to boto3's normal credential chain when unset |
| `BEDROCK_LLM_MODEL_ID` | No (default `qwen.qwen3-coder-next`) | Swap freely, but verify your AWS account actually has invoke entitlement for a given model first (catalog listing ≠ invokable) |
| `BEDROCK_MAX_TOKENS` | No (default `4096`) | Cap per-call output tokens; lower if you hit account-level rate limits and don't need long narrative output |
| `ENABLE_LANGFUSE_TRACING` | No (default varies) | Turn on/off Langfuse tracing + prompt management entirely |
| `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_HOST` | Only if tracing is on | **Note the name is `LANGFUSE_HOST`, not `LANGFUSE_BASE_URL`** — that typo has silently pointed tracing nowhere before |

---

## 6. Conventions and gotchas (read before touching backend code)

These aren't stylistic preferences — most are lessons from real bugs already found and fixed
in this codebase. Repeating them wastes time.

1. **Never do `from app.core.db import neo4j_driver` (or similar) at module level.**
   `init_db()` sets `neo4j_driver`/`qdrant_client` on the `app.core.db` module *after* other
   modules have already imported it — a bare `from ... import neo4j_driver` captures `None`
   permanently. Always `from app.core import db as core_db` and reference `core_db.neo4j_driver`
   dynamically.
2. **The Podman/Docker build context is the repo root, not `backend/`.** `backend/Dockerfile`
   copies both `backend/` and `frontend/` into the image — `main.py` mounts `frontend/`
   unconditionally via `StaticFiles` and crashes at startup if it's missing. Build with
   `podman build -f backend/Dockerfile -t emios-backend .` from the repo root.
3. **Compose `depends_on` needs `condition: service_healthy` for Neo4j.** Neo4j can take
   15-30s+ to accept Bolt connections on first boot; `init_db()` tries once with no retry. A
   plain `depends_on: [neo4j]` starts the backend before Neo4j is actually ready, and it falls
   back to in-memory for the rest of that process's life.
4. **`langfuse` must stay pinned `<3.0.0`.** `app/core/observability.py` uses the v2 SDK API
   (`langfuse.callback.CallbackHandler`, `.trace()`, `.generation()`), which v3+ removed.
5. **New tunable numbers go in `app/core/constants.py`**, not inline in business logic.
6. **New errors subclass `EMIOSException`** (`app/core/exceptions.py`) for a consistent JSON
   error response via the handlers registered in `main.py`.
7. **Degrade gracefully, don't hard-fail on missing infra.** Try the real dependency, fall back
   to in-memory/deterministic, log a warning — the house style throughout. Tests in particular
   should never require live Postgres/Neo4j (see `backend/tests/conftest.py`'s SQLite override).
8. **Keep `/api/v1` entity columns portable** (`String`, `Integer`, `Float`, `DateTime`, `Text`,
   generic `JSON`) — avoid Postgres-only types (`JSONB`/`ARRAY`/native `UUID`), so the same
   models run against Postgres in production and SQLite in tests.
9. **CSV/JSON ingestion is deliberately forgiving** (case-insensitive header aliases, duplicate
   IDs overwrite-with-warning, invalid edges skip-with-warning, never hard-reject a whole file
   over one bad row). Match that tolerance in any new ingestion code.
10. **Repository / Service / Router layering is not optional** for `/api/v1` code: routers only
    do request validation + DI + response shaping, business logic lives in `services_v1/`, DB
    access lives in `repositories/`. Use `assessments.py` + `assessment_service.py` +
    `assessment_repository.py` as the reference example.
11. **Schema changes go through Alembic migrations, not `create_all()`.** After changing an
    entity in `app/entities/`, run `alembic revision --autogenerate -m "..."` from `backend/`,
    review the generated file under `alembic/versions/` (autogenerate is a starting point, not
    gospel), commit it — the next app startup applies it automatically (`app/db/migrate.py`,
    called from `main.py`'s startup hook). See `backend/alembic/README`.
12. **`POST /api/v1/assessments/{id}/uploads` is for RAG documents, not structured topology.**
    It chunks/embeds whatever text it can extract — it does NOT parse CSV/JSON into graph
    nodes/edges. The digital twin graph is built either by Document Discovery
    (`POST .../discover` / `.../discover/stream`, LLM-extracted from free-text documents) or by
    directly posting structured data to `POST .../graph`.
13. **`frontend/dist` must exist before the backend will start.** `main.py` raises at import
    time if it's missing — run `npm run build` inside `frontend/` first. This also means
    `pytest` needs the frontend built at least once, since the test suite imports `main.app`.
14. **Agent output formatting is deterministic, not LLM-authored.** Every pipeline agent
    computes its real structured data (scores, tables, wave sequences) in plain Python *before*
    calling the LLM — the LLM call only supplies a short plain-English narrative
    interpretation. `app/agents/response_formatter.py` is what actually builds the
    tables/bullet-lists/Mermaid flowcharts shown in the UI, from that real data. If agent output
    ever looks wrong (missing table, wrong numbers), check the Python computation and the
    formatter first — the prompt is very unlikely to be the cause, by design.
15. **Frontend "run in the background, survive navigation" providers follow one pattern.**
    `discovery-run-context.tsx` / `planner-run-context.tsx` / `report-run-context.tsx` are all
    the same shape: a context mounted once at the app root (`App.tsx`), a `startRun(assessmentId)`
    that kicks off work independent of the current route, and a small persistent status panel
    stacked in the bottom-right notification column. Follow this pattern for any new
    long-running background operation rather than page-local `useState`.

---

## 7. Running tests

```bash
# from the repo root
PYTHONPATH=backend pytest backend/tests          # macOS/Linux
$env:PYTHONPATH="backend"; pytest backend/tests   # Windows PowerShell
```
Tests never require live Postgres/Neo4j/Qdrant — they run against an in-memory SQLite engine
via a dependency override (`backend/tests/conftest.py`). They **do** need `frontend/dist` to
exist (see gotcha #13) since the suite imports `main.app`. 193 tests currently pass.

### Verifying against real infra (do this before anything deploy-related)
```bash
curl http://localhost:8000/api/health
# expect: {"status":"healthy","database":"connected","api":"online"}
```
If `database` says `"unconnected"` while Neo4j/Postgres containers are clearly running, don't
assume it's fine — see gotcha #1, it's exactly this symptom.

---

## 8. Project structure

```
backend/
  main.py                    # FastAPI app, CORS, latency logging, exception handlers, SPA static mount
  app/
    core/
      config.py              # pydantic-settings Settings, reads backend/.env
      db.py                  # Neo4j + Qdrant client init (best-effort; sets client to None on failure)
      storage.py             # S3 client init + ObjectStorage (local-disk fallback)
      llm_provider.py        # LLM provider chain (Bedrock preferred) + invoke_with_fallback()
      embeddings.py          # Embedding provider chain (Bedrock Titan preferred) for RAG
      constants.py           # ALL magic numbers for simulation/costing/planner thresholds
      exceptions.py          # EMIOSException subclasses -> mapped to JSON error responses
      observability.py       # Langfuse tracing + prompt management (needs langfuse<3.0.0)
      security.py            # bcrypt password hashing + PyJWT encode/decode
    api/
      endpoints.py            # legacy /api/* routes (health, upload, graph, simulate, plan, chat)
      v1/                     # /api/v1/* routes - auth, assessments, uploads, discovery, waves,
                               # graph, simulate, agent-runs, reports, dashboard, chat
    db/                       # SQLAlchemy async engine/session for /api/v1
    entities/                 # SQLAlchemy ORM models
    repositories/             # /api/v1 data access layer - no business logic here
    services_v1/               # /api/v1 business logic - repositories in, domain errors out
    schemas_v1/                # Pydantic v2 request/response schemas + response envelope
    dependencies/               # FastAPI DI providers (DB session, service factories, auth)
    services/
      neo4j_service.py        # graph CRUD + demo dataset loader + in-memory fallback store
      simulation_engine.py    # cascading-failure BFS + Monte Carlo triangular sampling
      document_processing_service.py  # extract -> chunk -> embed -> store, for RAG
      vector_search_service.py        # Qdrant upsert/search, scoped per-assessment
    agents/
      state.py, workflow.py, prompts.py  # the 12-agent Master Orchestrator pipeline
                                          # (run_full_assessment_stream) plus the older
                                          # 4-agent Discovery/Dependency/Risk/Planner
                                          # negotiation loop (run_agent_negotiation)
      response_formatter.py    # deterministic Markdown/table/Mermaid rendering of agent output
      tools.py                 # agent tool-use (on-demand schema/document lookups)
    alembic/                    # DB migrations - see gotcha #11
  tests/                      # pytest suite
frontend/
  src/
    lib/
      *-run-context.tsx        # background-run providers (discovery/planner/report) - see gotcha #15
      theme-context.tsx        # light/dark theme toggle
    components/                # shared UI (AppShell, panels, Markdown+Mermaid renderer, KpiCard, ...)
    pages/                     # one file per route
  dist/                        # npm run build output - main.py serves this; gitignored, not checked in
docker-compose.yml             # local dev: neo4j + qdrant + postgres
docker-compose.prod.yml        # deployment: backend + postgres + neo4j
scripts/deploy/                # AWS Lightsail/EC2 provisioning + deploy automation - see section 11
Meridian_Migration_Assessment/  # sample "raw documents" demo dataset (BRD/HLD/inventory style)
Meridian_Sample_Graph/          # sample pre-built graph (XLSX/CSV/JSON) for quick seeding
Northwind_Migration_Assessment/ # large, realistic 15-category enterprise document set for demos
Northwind_Expected_Graph/       # the graph Document Discovery *should* extract from the above -
                                 # used to sanity-check extraction quality, see its own README
sample_input/                   # assorted small sample files (CSV/DOCX/TXT/zip) for quick manual testing
```

### Two API surfaces, on purpose
- **`/api/*`** (legacy, `app/api/endpoints.py`): `GET /api/health`, `POST /api/upload`,
  `GET /api/graph`, `POST /api/reset`, `POST /api/simulate`, `POST /api/plan`, `POST /api/chat`,
  `GET /api/observability/status`. Returns Pydantic models **unwrapped**. Has its own passing
  tests — don't change its response shapes without updating those.
- **`/api/v1/*`** (`app/api/v1/`): the durable, multi-user, database-backed surface. Returns a
  consistent envelope: `{"success": true, "message": "...", "data": {...}}` on success,
  `{"success": false, "message": "...", "errors": [...]}` on failure. All new feature work goes
  here.

Currently live under `/api/v1` (grouped by resource):
- **Auth**: `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
- **Assessments**: `POST /assessments`, `GET /assessments`, `GET /assessments/{id}`,
  `PATCH /assessments/{id}/status`
- **Uploads (RAG)**: `POST /assessments/{id}/uploads`, `POST /assessments/{id}/uploads/zip`,
  `POST /assessments/{id}/uploads/zip/stream` (SSE progress for large archives),
  `GET /assessments/{id}/uploads`
- **Document Discovery**: `POST /assessments/{id}/discover`,
  `POST /assessments/{id}/discover/stream` (SSE), `GET /assessments/{id}/discover/nodes.csv`,
  `GET /assessments/{id}/discover/edges.csv`
- **Digital twin graph**: `POST /assessments/{id}/graph`, `GET /assessments/{id}/graph`
- **What-if simulation**: `POST /assessments/{id}/simulate`, `GET /assessments/{id}/simulate`
- **Migration waves**: `POST /assessments/{id}/waves`, `GET /assessments/{id}/waves`
- **Wave Planner (12-agent pipeline)**: `POST /assessments/{id}/agent-runs`,
  `POST /assessments/{id}/agent-runs/stream` (SSE - what the real UI uses),
  `GET /assessments/{id}/agent-runs/latest`, `GET /assessments/{id}/agent-runs`
- **Report**: `POST /assessments/{id}/report`, `GET /assessments/{id}/report`,
  `POST /assessments/{id}/report/feedback`, `POST /assessments/{id}/report/revise`,
  `GET /assessments/{id}/report/history`, `GET /assessments/{id}/report/history/{version}`,
  `GET /assessments/{id}/report/pdf`, `POST /assessments/{id}/migration-plan`,
  `GET /assessments/{id}/migration-plan/pdf`
- **Chat (RAG)**: `POST /assessments/{id}/chat`
- **Dashboard**: `GET /dashboard/summary`

---

## 9. Sample / demo data

- `Meridian_Migration_Assessment/` — a small, quick "raw documents" set (an XLSX inventory, a
  PDF landscape overview, an XLSX integration map) for a fast end-to-end demo.
- `Meridian_Sample_Graph/` — a pre-built graph (XLSX/CSV/JSON) plus a `seed_assessment.py`
  script to skip document upload entirely and jump straight to a populated digital twin.
- `Northwind_Migration_Assessment/` — a large, realistic 15-category enterprise document set
  (executive summaries, architecture docs, API catalogs, CMDB exports, security assessments,
  cost projections, etc.) for a full, credible demo of Document Discovery at scale.
- `Northwind_Expected_Graph/` — the graph Document Discovery is expected to extract from the
  Northwind set, plus `generate_expected_graph.py` to regenerate it — used to sanity-check
  extraction quality after prompt/extractor changes. See its own `README.md`.
- `sample_input/` — assorted small files (CSV/DOCX/TXT/zip) for quick manual upload testing.

---

## 10. Deployment (AWS)

Validated path: Podman on an Ubuntu Lightsail instance, `docker-compose.prod.yml` (backend +
postgres + neo4j; Qdrant intentionally excluded — nothing queries it in the deployed config).

**Start with `scripts/deploy/RUNBOOK.md`** — the full, step-by-step deployment procedure
(AWS/IAM setup, credential handling, troubleshooting index), written after a complete
successful deployment and meant to be followed as-is. `scripts/deploy/README.md` covers what
each script does; `provision.py`/`provision_ec2.py` create the instance, `deploy.sh` ships code
and brings the stack up, `teardown.py`/`teardown_ec2.py` delete the instance when done.

```bash
# On the instance, after installing podman:
sudo systemctl enable --now podman.socket
git clone <this-repo-url> && cd <repo>
cp backend/.env.production.example backend/.env.production   # fill in real values
sudo DOCKER_HOST=unix:///run/podman/podman.sock docker-compose -f docker-compose.prod.yml --env-file backend/.env.production up -d --build
curl http://localhost:8000/api/health   # must say "database":"connected"
```

**Budget note**: Lightsail bills hourly (capped at the monthly rate) — a `medium_3_0`
(4GB/2vCPU) instance is roughly $0.033/hr. Run `scripts/deploy/teardown.py` when not actively
working on the deploy to stop the meter; it leaves the S3 bucket/data alone unless passed
`--delete-bucket`.

---

## 11. Known limitations (don't assume otherwise)

- **Auth + per-owner authorization** is enforced on every `/assessments/{id}/...` route
  (`app/dependencies/auth.py`'s `require_assessment_owner`) — 404s, not 403s, so a caller can't
  distinguish "doesn't exist" from "exists but isn't yours".
- **No CI** — tests currently run manually.
- **RAG retrieval quality depends on what's actually configured.** Without real Bedrock/OpenAI
  credentials, embeddings fall back to a deterministic hash-based pseudo-embedder — the
  pipeline runs and is fully testable, but retrieved chunks won't be semantically meaningful.
- **Human review on reports is intentionally simplified** (thumbs up/down + comment, no
  reviewer role or approval gate).
- **The legacy `/api/*` surface and the 4-agent `run_agent_negotiation` loop still exist** but
  aren't what the real UI drives — the Wave Planner UI uses the 12-agent
  `run_full_assessment_stream` pipeline via `/api/v1`. Don't assume the legacy surface reflects
  current agent behavior.

---

## 12. Team / branches

Original task allocation (from the hackathon team task guide):

| Person | Primary focus |
|---|---|
| Rohan | Presentation, demo narrative, screenshots |
| Bhargavi | LLM orchestration, agents, simulation/assessment reasoning, explainability |
| Kunal | API contracts, backend routes, shared response models |
| Kirtan | Ingestion, graph, integration, backend data flow |
| Shweta | Frontend, UI polish, demo screens, user journey |

The original plan was separate feature branches off `develop`, merged in dependency order. In
practice, this repo's active default branch is **`feature/end-to-end-assessment-platform`**
(check `git remote show origin` if in doubt) — most work has landed there directly rather than
through the originally-planned per-owner branches. A `ui-redesign` branch exists with a light
enterprise theme (now merged into the app as the default theme, with the original dark
"Blackout" theme still available via the toggle - see section 2) and a `Code_Refactoring`
branch for structural cleanup work.
