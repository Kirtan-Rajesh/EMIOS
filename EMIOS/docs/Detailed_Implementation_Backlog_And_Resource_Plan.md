# EMIOS Implementation Backlog & 2-Day Resource Execution Plan

This master document serves as the single source of truth for the engineering team. It maps out the compressed **2-day execution schedule** for Tejas, Shweta, Kirtan, Bhargavi, and Kunal, and provides the complete, technical implementation details for every backlog task.

---

## Part 1: Team Roles & 2-Day Daily Schedule

### Team Composition
* **Tejas Lot (Architecture & CI/CD)**: Code reviews, core repository contracts, GitHub Actions testing workflows, and final E2E verification.
* **Bhargavi Cherukupalli (DevOps, LLMs & Tracing)**: Multi-model LLM support (Gemini + OpenAI), concrete database repository drivers, dynamic model telemetry, and Langfuse tracing.
* **Shweta Gumaste (Data & Fallbacks)**: Fallback database repository abstractions, local caching logic, and transparent fallback integration.
* **Kirtan Rajesh (Security & Config)**: CORS access rules, settings config loading, and API origin whitelist validation.
* **Kunal Bhosale (Frontend & Bundling)**: Node npm environment setups, local asset compilation (Vite), and frontend asset integration

### 2-Day Sprint Roadmap

#### Day 1: Contract Setup, Local Dev, Security, and Multi-Model AI Foundations
* **Tejas Lot**: 
  * Define and merge `GraphRepository` interface contract (**TS-101**).
* **Shweta Gumaste**: 
  * Write `InMemoryGraphRepository` fallback database code (**TS-102**).
* **Kirtan Rajesh**: 
  * Add configuration settings and parse CORS origins whitelist from dotenv (**TS-201**).
* **Bhargavi Cherukupalli**: 
  * Add Gemini package dependency and configure Gemini as alternative LLM provider (**TS-302**).
* **Kunal Bhosale**: 
  * Initialize Vite and setup the offline-capable npm dependency environment (**TS-401**).

#### Day 2: Integration, Telemetry, CI/CD pipelines, and E2E Verification
* **Tejas Lot**: 
  * Configure GitHub Actions CI workflow script pipeline (**TS-501**).
* **Bhargavi Cherukupalli**: 
  * Integrate concrete `Neo4jGraphRepository` driver logic into API controllers (**TS-103**).
  * Register Langfuse CallbackHandlers to track agent negotiation loops (**TS-301**).
* **Kirtan Rajesh**: 
  * Code CORS request filter integration tests (**TS-202**).
* **Kunal Bhosale**: 
  * Bundle React visualizer scripts and statically mount Vite build assets in FastAPI (**TS-402**).

---

## Part 2: Detailed Task Backlog Specifications

### Epic 1: Clean Architecture & Database Abstraction

#### Task: TS-101 — Define Abstract GraphRepository Base Interface
* **Owner**: Tejas Lot
* **Objective**: Create Python abstract class for all graph CRUD operations.
* **What to do**:
  * Create `backend/app/application/interfaces/graph_repository.py`.
  * Define `GraphRepository(ABC)` with abstract methods `get_graph()`, `reset_and_populate_graph()`, and `get_demo_dataset()`.
* **Estimated Effort**: 3 Hours

#### Task: TS-102 — Write In-Memory Fallback Repository
* **Owner**: Shweta Gumaste
* **Objective**: Implement local dictionary-based database fallback logic.
* **What to do**:
  * Create `backend/app/infrastructure/database/in_memory_repository.py`.
  * Move local caching logic and raw dataset loaders inside this class.
* **Estimated Effort**: 4 Hours

#### Task: TS-103 — Integrate Neo4j Concrete Driver Repository
* **Owner**: Bhargavi Cherukupalli
* **Objective**: Map Cypher database commands to the graph repository structure.
* **What to do**:
  * Create `backend/app/infrastructure/database/neo4j_repository.py`.
  * Wire database sessions and replace direct driver imports inside FastAPI endpoints with repository calls.
* **Estimated Effort**: 6 Hours

---

### Epic 2: Security & Configuration Rules

#### Task: TS-201 — Dotenv Config & CORS Whitelist Setup
* **Owner**: Kirtan Rajesh
* **Objective**: Load and parse authorized browser host origins dynamically.
* **What to do**:
  * Add `CORS_ORIGINS: List[str] = ["http://localhost:8000"]` settings in `config.py`.
  * Load origins inside FastAPI `CORSMiddleware` setup in `main.py`.
* **Estimated Effort**: 3 Hours

#### Task: TS-202 — Security Domain Integration Tests
* **Owner**: Kirtan Rajesh
* **Objective**: Verify that CORS rejects non-whitelisted cross-origin domains.
* **What to do**:
  * Write request tests in `tests/test_api.py` targeting API endpoints with unauthorized `Origin` headers.
* **Estimated Effort**: 3 Hours

---

### Epic 3: Multi-Model LLM Setup & Observability

#### Task: TS-301 — Register Langfuse Tracing Spans
* **Owner**: Bhargavi Cherukupalli
* **Objective**: Push multi-agent negotiation logs to the Langfuse cloud/self-hosted collector.
* **What to do**:
  * Initialize `CallbackHandler` using credentials.
  * Inject callbacks array to `run_agent_negotiation` graph compilation parameters.
* **Estimated Effort**: 5 Hours

#### Task: TS-302 — Support Gemini as Alternative LLM
* **Owner**: Bhargavi Cherukupalli
* **Objective**: Support Google Gemini (`gemini-1.5-flash`) as alternative model.
* **What to do**:
  * Add `langchain-google-genai` to dependencies.
  * Set `GEMINI_API_KEY` in Settings, and instantiate `ChatGoogleGenerativeAI` if configured.
  * Dynamically report the active model name to `record_generation` tracing logs.
* **Estimated Effort**: 6 Hours

---

### Epic 4: Offline Frontend Bundling

#### Task: TS-401 — Initialize Vite & Package Environment
* **Owner**: Kunal Bhosale
* **Objective**: Setup localized npm dependencies to package React libraries.
* **What to do**:
  * Create `frontend/package.json` and install React, Vis-Network, and Recharts.
  * Create `frontend/vite.config.js` to target bundle output paths.
* **Estimated Effort**: 6 Hours

#### Task: TS-402 — Static Assets Serving
* **Owner**: Kunal Bhosale
* **Objective**: Serve compiled JavaScript assets directly from local storage.
* **What to do**:
  * Replace CDN stylesheet/script references inside `frontend/index.html` with bundled files paths.
  * Mount compiled build folders (`dist/`) statically under FastAPI server.
* **Estimated Effort**: 6 Hours

---

### Epic 5: CI/CD Pipeline Automation

#### Task: TS-501 — GitHub Actions CI Configuration
* **Owner**: Tejas Lot
* **Objective**: Automate code validation checks on new repository commits.
* **What to do**:
  * Create `.github/workflows/ci.yml`.
  * Write build checks triggers to run `pytest backend/tests` on every branch pull request.
* **Estimated Effort**: 4 Hours
