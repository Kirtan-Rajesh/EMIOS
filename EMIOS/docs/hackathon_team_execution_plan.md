# EMIOS Hackathon Team Execution Plan

## 1. Objective

Build a reliable, demo-ready EMIOS experience for the hackathon with minimal conflict, clear ownership, and a deployment path that fits a small AWS budget.

This plan is based on the actual repository structure and the existing backend modules, not on a generic hackathon template.

Assumptions:
- 5 team members
- 3 available VDIs
- 4 people work in parallel, with 2 people sharing each VDI where needed
- 1 person may be less reliable and should not own a critical path
- The goal is a working, explainable demo, not a perfect enterprise platform

---

## 2. What the Project Already Has

The repository already contains a strong starting point:
- FastAPI backend entrypoint in backend/main.py
- API routes in backend/app/api/endpoints.py
- Pydantic schemas in backend/app/models/schemas.py
- Graph and simulation services in backend/app/services/
- Multi-agent workflow in backend/app/agents/workflow.py
- Tests under backend/tests/
- A basic frontend shell in frontend/

This means the team should focus on stabilization, integration, and presentation rather than building everything from scratch.

---

## 3. What We Should Prioritize for the Hackathon

The project should be judged on three things:
1. Can the system ingest a sample architecture and produce something meaningful?
2. Can it show a clear migration assessment and wave plan?
3. Can it be demonstrated smoothly from a live URL?

That means the winning scope is:
- upload sample metadata
- show graph-based digital twin
- show simulation/risk results
- show migration waves
- show a polished dashboard

Anything beyond that is optional for this hackathon.

---

## 4. Team Assignments Based on the Actual Codebase

### Member 1 — Backend Lead / API & Integration Owner
Role: owns the system backbone and keeps all pieces talking to each other.

Responsibilities:
- Own the API contract and backend integration
- Keep the routes, schemas, and services aligned
- Own health checks, error handling, and deployment readiness
- Coordinate all shared changes

Primary files:
- backend/main.py
- backend/app/api/endpoints.py
- backend/app/models/schemas.py
- backend/app/core/config.py
- backend/app/core/exceptions.py

Must deliver first:
- A stable API surface for upload, graph, simulate, plan, and health
- One working end-to-end path from upload to results

Why this person matters most:
- They prevent the team from breaking the app while others work independently

---

### Member 2 — Ingestion & Parser Specialist
Role: owns the ingestion path and turns raw files into normalized system data.

Responsibilities:
- Make uploads work reliably with JSON/CSV-like sample input
- Normalize fields into node and edge structures
- Handle duplicate IDs, missing values, and invalid references
- Produce structured data for the graph and simulation engine

Primary files:
- backend/app/api/endpoints.py
- backend/app/models/schemas.py
- any new parsing helper modules if needed

Must deliver first:
- A clean upload flow that produces nodes and edges from sample data
- Validation warnings/errors in a predictable format

This is the most important functional module for the hackathon because the rest of the system depends on it.

---

### Member 3 — Graph & Digital Twin Specialist
Role: owns the graph model, persistence, and digital twin representation.

Responsibilities:
- Make the graph load from ingested data
- Ensure the graph can be returned and displayed by the UI
- Understand the dependency structure and how it affects simulation

Primary files:
- backend/app/services/neo4j_service.py
- backend/app/services/simulation_engine.py

Must deliver first:
- A working /api/graph endpoint returning valid graph data
- A digital twin payload that is understandable to the frontend

This person should work closely with Member 2 and Member 4.

---

### Member 4 — Assessment Engine & Agent Workflow Specialist
Role: owns the logic that makes EMIOS feel intelligent.

Responsibilities:
- Make the simulation engine deterministic and explainable
- Ensure cascading failure and Monte Carlo outputs are useful
- Make planner and risk logic produce realistic migration waves
- Keep the agent workflow connected to the backend

Primary files:
- backend/app/services/simulation_engine.py
- backend/app/agents/workflow.py
- backend/app/agents/state.py
- backend/app/agents/prompts.py

Must deliver first:
- One reliable simulation response
- One reliable planning response
- One clear assessment summary for the demo

This is the module that creates the “AI” value for judges.

---

### Member 5 — Frontend & Demo Specialist
Role: owns the UI experience and the presentation flow.

Responsibilities:
- Make the dashboard and screens feel polished and enterprise-like
- Connect the UI to the backend endpoints
- Prepare the demo narrative and screen flow
- Support QA and issue triage

Primary files:
- frontend/index.html
- frontend/index.css
- any frontend components added during the hackathon

Must deliver first:
- A simple but polished UI that shows the upload → assessment → graph → plan flow
- A coherent story that judges can follow in under 5 minutes

This person should not be made responsible for the critical backend path.

---

## 5. What Should Be Built First, in Order

This is the correct order for the team.

### Phase 1 — Stabilize the shared contract
Who: Member 1

Goal:
- Make sure the backend responses are consistent and documented
- Ensure the API can support the frontend in a simple way

Why first:
- The rest of the team will build against it
- This avoids rework and broken integrations

Deliverables:
- /api/health
- /api/upload
- /api/graph
- /api/simulate
- /api/plan

---

### Phase 2 — Make ingestion work reliably
Who: Member 2

Goal:
- Convert sample metadata into usable node/edge data

Why second:
- Everything else depends on having valid data to work with

Deliverables:
- Sample upload succeeds
- Nodes and edges are created without obvious errors

---

### Phase 3 — Make the graph readable and usable
Who: Member 3

Goal:
- Ensure the digital twin is available through the API and can be shown to the user

Why third:
- The graph view is one of the strongest demo components

Deliverables:
- A graph payload that is clean enough for the frontend to display

---

### Phase 4 — Make the assessment logic meaningful
Who: Member 4

Goal:
- Provide simulation and migration wave outputs based on the graph

Why fourth:
- This is the “intelligence” part of the platform and should be wired once the graph exists

Deliverables:
- One realistic risk assessment
- One clear migration plan

---

### Phase 5 — Connect the UI to the backend
Who: Member 5 with support from Member 1

Goal:
- Turn the backend results into a polished product experience

Why fifth:
- The UI should reflect the actual backend output, not a fake one

Deliverables:
- Upload screen
- Assessment screen
- Graph screen
- Plan screen

---

### Phase 6 — Deploy and prepare the demo
Who: Member 1 + Member 5

Goal:
- Put the app online and make the demo smooth

Deliverables:
- Live URL
- Demo script
- Screenshots or short walkthrough

---

## 6. Dependency Map

### Hard dependencies
These must happen in order:
1. Shared API contract
2. Ingestion/parser output
3. Graph data availability
4. Simulation/planning output
5. Frontend integration
6. Deployment

### Soft dependencies
These can happen in parallel:
- Member 5 can build UI screens using mock data while Members 2–4 prepare the real backend flow
- Member 3 and Member 4 should coordinate on the shape of graph data used by simulation

---

## 7. What Each Member Should Not Do

To reduce conflict and confusion:
- Member 2 should not rewrite the API routes unless required
- Member 3 should not redesign schemas unless Member 1 approves it
- Member 4 should not change the frontend structure
- Member 5 should not rewrite backend logic in a way that affects the API contract
- Member 1 should be the gatekeeper for shared files

---

## 8. Recommended Working Rules for the Team

1. One shared sample dataset must be used by everyone.
2. Every new API field must be agreed on before implementation.
3. Do not change the same file in parallel without coordination.
4. Each person should finish one feature completely before moving to the next.
5. The team should prefer a reliable demo over a perfect architecture.

---

## 9. Suggested Daily Plan

### Day 1 — Alignment and backend foundation
- Member 1: define the core API contract and shared response shapes
- Member 2: prepare the sample ingestion schema
- Member 3: confirm the graph payload format
- Member 4: confirm the assessment output format
- Member 5: sketch the UI pages and demo flow

### Day 2 — Core functionality
- Member 2: make upload and parser work
- Member 3: make graph retrieval work
- Member 4: make simulation and planning work
- Member 1: connect endpoints and make the system stable

### Day 3 — UI and integration
- Member 5: connect the frontend to the backend
- Member 1: fix any contract mismatches
- Member 3/4: ensure their outputs look useful in the UI

### Day 4 — Demo polish and deployment
- Member 5: polish screens and prepare story
- Member 1: deploy and test the live flow
- Everyone: test the full journey end to end

---

## 10. How to Handle the Weak Contributor

The weak contributor should not own a critical dependency path.

Best assignment:
- demo narrative
- sample data preparation
- UI polish and screenshots
- QA checklist
- presentation notes

This keeps the project moving even if that person is inconsistent.

---

## 11. Final Recommendation

The team should not try to build a perfect enterprise platform. The smartest hackathon strategy is:
- make the core flow work end to end
- make the outputs understandable
- make the presentation polished
- deploy it early

The existing EMIOS repo already has the backbone. The team should now focus on making the current pieces consistently work together and look impressive in a live demo.

### Member 1 — Lead Architect / Backend Integrator
Role: owns architecture, API contracts, integration, and overall system health.

Responsibilities:
- Own the main backend architecture and integration points
- Define all shared schemas and payloads
- Own the API routes and request/response contracts
- Coordinate between members and prevent merge conflicts
- Own final demo orchestration

Primary files:
- backend/main.py
- backend/app/api/endpoints.py
- backend/app/models/schemas.py
- backend/app/core/config.py
- backend/app/core/exceptions.py

Deliverables:
- Stable API layer
- Standard error handling
- Health endpoints
- Upload and simulation endpoints working end-to-end

Input / Output:
- Input: frontend requests, parsed graph data, simulation payloads
- Output: normalized API responses, structured errors, demo-ready payloads

---

### Member 2 — Discovery & Parser Specialist
Role: owns ingestion, document parsing, metadata parser, and normalization.

Responsibilities:
- Build the ingestion pipeline for JSON/CSV/metadata uploads
- Normalize files into systems and dependencies
- Detect duplicates, missing fields, and invalid references
- Produce structured node/edge data

Primary files:
- backend/app/services/neo4j_service.py (partially)
- backend/app/services/parser or ingestion logic (if added)
- backend/app/models/schemas.py (shared structures)

Deliverables:
- Upload endpoint accepts sample data and produces valid node/edge structure
- Validation warnings and error reporting
- Clean ingestion from sample files and demo data

Input / Output:
- Input: BRD/FRD/HLD/LLD/schema/metadata/Swagger/CSV/JSON
- Output:
  - nodes: list of systems with metadata
  - edges: list of dependency relationships
  - warnings/errors: validation details

Suggested output shape:
```json
{
  "nodes": [
    {
      "id": "billing_service",
      "name": "Billing Service",
      "type": "Microservice",
      "business_value": "High",
      "migration_complexity": "High",
      "annual_cost": 30000,
      "runtime": "Go 1.20"
    }
  ],
  "edges": [
    {
      "source": "billing_service",
      "target": "billing_db",
      "type": "DB",
      "criticality": "High"
    }
  ]
}
```

---

### Member 3 — Graph / Digital Twin Specialist
Role: owns graph data modeling, relationship logic, and digital twin representation.

Responsibilities:
- Build and maintain the enterprise digital twin model
- Define dependency graph semantics
- Implement graph queries and relationship traversal
- Provide graph data for the UI and simulation engine

Primary files:
- backend/app/services/neo4j_service.py
- backend/app/services/simulation_engine.py (shared inputs)

Deliverables:
- Graph loads successfully from uploaded data
- Graph can be fetched by the frontend
- Dependency traversal across nodes works

Input / Output:
- Input: normalized nodes and edges
- Output:
  - graph data for frontend visualization
  - dependency paths for impact analysis

Recommended graph model:
- Node type: System
- Relationship types: DEPENDS_ON, RUNS_ON, USES_DB, CALLS_API

Example:
```json
{
  "nodes": [
    {"id": "customer_portal", "label": "Customer Portal", "type": "Application"},
    {"id": "payment_service", "label": "Payment Service", "type": "Application"},
    {"id": "oracle_db", "label": "Oracle DB", "type": "Database"}
  ],
  "edges": [
    {"source": "customer_portal", "target": "payment_service", "type": "CALLS"},
    {"source": "payment_service", "target": "oracle_db", "type": "USES_DB"}
  ]
}
```

---

### Member 4 — Assessment Engine / Agent Workflow Specialist
Role: owns simulation, risk, planner, and agent logic.

Responsibilities:
- Build the risk and complexity engine
- Implement cascading failure simulation
- Implement Monte Carlo cost/time estimation
- Implement migration wave planning
- Connect the agent workflow to the backend

Primary files:
- backend/app/services/simulation_engine.py
- backend/app/agents/state.py
- backend/app/agents/workflow.py
- backend/app/agents/prompts.py

Deliverables:
- Simulation endpoint returns meaningful values
- Planner endpoint returns migration waves
- Agent workflow can produce structured assessment summary

Input / Output:
- Input: graph nodes, edges, target component, migration assumptions
- Output:
  - impacted nodes
  - critical paths
  - revenue at risk
  - expected duration and cost
  - recommended migration waves

Suggested output shape:
```json
{
  "target_id": "billing_service",
  "impacted_nodes": ["billing_service", "billing_db"],
  "revenue_at_risk": 120000,
  "total_hosting_cost": 30000,
  "monte_carlo": {
    "expected_duration": 6,
    "expected_cost": 180000,
    "confidence_90_duration": [5, 8],
    "confidence_90_cost": [150000, 220000]
  },
  "waves": [
    {"wave": 1, "components": ["billing_db"], "rationale": "Database first"},
    {"wave": 2, "components": ["billing_service"], "rationale": "Application after dependency stabilization"}
  ]
}
```

---

### Member 5 — Frontend / Demo / QA Support
Role: owns UI polish, demo flow, and lightweight QA.

Responsibilities:
- Build the dashboard, upload page, graph view, assessment view, and simulation view
- Make the app feel enterprise-grade and demo-ready
- Create sample data and demo narrative
- Record issues and hand them to the backend team

Primary files:
- frontend/index.html
- frontend/index.css
- any frontend component files added for the hackathon UI

Deliverables:
- Functional UI with sample data
- Clear navigation between upload, assessment, graph, and plan screens
- Demo flow that can be shown in 5–7 minutes

Input / Output:
- Input: API responses from backend
- Output: polished UI and presentation-ready views

Important: This person should not own core backend logic. Their work should be independent and lightweight enough that the project can still progress even if they are inconsistent.

---

## 5. Recommended Workload Split to Avoid Conflict

### Shared ownership boundaries
- Member 1 owns shared contracts and API layer
- Member 2 owns ingestion/parsing
- Member 3 owns graph and digital twin
- Member 4 owns simulation, risk, planning, and agents
- Member 5 owns frontend and demo polish

### Files that should not be edited by multiple people
- backend/app/models/schemas.py — owned by Member 1 only
- backend/app/api/endpoints.py — owned by Member 1 only
- backend/app/services/neo4j_service.py — owned by Member 3 only
- backend/app/services/simulation_engine.py — owned by Member 4 only
- backend/app/agents/workflow.py — owned by Member 4 only
- frontend files — owned by Member 5 only

### Rule for all members
- Do not change shared files without first checking with Member 1
- If a feature needs a new endpoint or request shape, first update the schema and tell the team

---

## 6. Detailed Execution Sequence

The key idea is simple: first define the contracts, then build the ingestion, then the graph, then the simulation, then the UI, and only at the end do deployment and polishing.

### Step 0 — Team kickoff and alignment (30–45 minutes)
Who acts:
- Everyone

What to do:
- Agree on the exact demo story
- Decide which 3 screens matter most for judges
- Agree on the sample customer and sample system architecture
- Decide on the minimum viable feature set

Must be completed before coding:
- One shared sample dataset
- One shared API contract list
- One agreed demo flow

Output:
- A single document with the final scope
- A decision on what is “must-have” vs “nice-to-have”

---

### Step 1 — Define the shared contract layer (1–2 hours)
Who acts:
- Member 1

What to do:
- Finalize the request/response structures for upload, graph, simulate, plan, and health
- Add schema definitions for nodes, edges, waves, and assessment summary
- Define the error response format

Why this comes first:
- It avoids mismatches between backend and frontend
- It prevents rework later

Must be done before:
- Frontend integration
- Simulation logic
- Graph implementation

Deliverables:
- Stable Pydantic schemas
- Standard API response patterns

Example contract:
```json
POST /api/upload
{
  "nodes": [],
  "edges": []
}
```

Response:
```json
{
  "status": "success",
  "parsed_nodes_count": 5,
  "parsed_edges_count": 4,
  "warnings": [],
  "errors": []
}
```

---

### Step 2 — Build ingestion and parser foundation (2–3 hours)
Who acts:
- Member 2

What to do:
- Create a parser that reads sample JSON/CSV input
- Normalize the input into nodes and edges
- Handle duplicates and invalid references
- Return a clean dataset to the backend

Dependencies:
- Depends on the schema from Member 1
- Does not depend on the graph or simulation logic

Must be completed before:
- Graph loading
- UI upload experience

Deliverables:
- Upload endpoint can ingest sample data successfully
- Validation warnings appear clearly
- Sample upload demonstrates one complete assessment

Output example:
```json
{
  "nodes": [
    {"id": "auth_service", "name": "Auth Service", "type": "Microservice"}
  ],
  "edges": [
    {"source": "auth_service", "target": "auth_db", "type": "DB"}
  ]
}
```

---

### Step 3 — Build graph persistence and graph retrieval (2–3 hours)
Who acts:
- Member 3

What to do:
- Store the parsed nodes/edges into graph storage
- Create graph retrieval logic for the frontend
- Build a simple digital twin view payload
- Make sure the graph can be loaded from the uploaded sample data

Dependencies:
- Depends on the output from Member 2
- Depends on the contract from Member 1

Must be completed before:
- UI graph panel can be shown
- Simulation logic can operate on graph structure

Deliverables:
- /api/graph returns a valid graph payload
- Graph nodes and edges appear in the UI

Output example:
```json
{
  "nodes": [
    {"id": "auth_service", "label": "Auth Service", "type": "Application"}
  ],
  "edges": [
    {"source": "auth_service", "target": "auth_db", "type": "USES_DB"}
  ]
}
```

---

### Step 4 — Build the assessment engine (2–4 hours)
Who acts:
- Member 4

What to do:
- Implement the risk and complexity logic
- Implement cascading failure simulation
- Implement cost/time estimation
- Implement migration wave planning

Dependencies:
- Depends on the graph data from Member 3
- Depends on the contract from Member 1

Must be completed before:
- Frontend can show assessment results
- Demo can show value beyond upload

Deliverables:
- Simulation endpoint returns meaningful outputs
- Planning endpoint returns migration waves

Output example:
```json
{
  "target_id": "auth_service",
  "impacted_nodes": ["auth_service", "auth_db"],
  "revenue_at_risk": 150000,
  "total_hosting_cost": 50000,
  "monte_carlo": {
    "expected_duration": 7,
    "expected_cost": 220000
  },
  "waves": [
    {"wave": 1, "components": ["auth_db"]},
    {"wave": 2, "components": ["auth_service"]}
  ]
}
```

---

### Step 5 — Wire the backend endpoints together (1–2 hours)
Who acts:
- Member 1

What to do:
- Connect the upload endpoint to the parser output
- Connect the graph endpoint to graph storage
- Connect simulate and plan endpoints to the assessment engine
- Ensure the API is stable and consistent

Dependencies:
- Depends on Steps 1–4

Deliverables:
- End-to-end backend path: upload → graph → simulation → plan

---

### Step 6 — Build the frontend UI shell (2–3 hours)
Who acts:
- Member 5

What to do:
- Create the main dashboard layout
- Build upload page
- Build assessment and graph view
- Build pages for simulation and plan output

Dependencies:
- Depends on the API contract from Member 1
- Can start early with mock data, but must switch to real API once available

Deliverables:
- A polished, clickable dashboard
- A working demo path from upload to results

---

### Step 7 — Integration and bug fixing (1–2 hours)
Who acts:
- Member 1 + Member 5

What to do:
- Connect the frontend to the backend
- Fix mismatches in response structure
- Ensure loading states and errors are handled

Deliverables:
- UI works on real data
- No obvious broken flow

---

### Step 8 — Deployment and final demo prep (1–2 hours)
Who acts:
- Member 1 + Member 5

What to do:
- Deploy the app to AWS
- Verify health endpoint and main routes
- Prepare the demo script and screenshots
- Make sure the app runs smoothly in the browser

Deliverables:
- Public URL working
- Demo flow ready

---

## 7. Dependency Map

### Hard dependencies
These must happen in order:
1. Shared schemas and API contract
2. Parser output format
3. Graph persistence and retrieval
4. Simulation/planning logic
5. Frontend integration
6. Deployment

### Soft dependencies
These can happen in parallel:
- Member 2 can work on parser while Member 1 defines the contract
- Member 5 can build the UI shell using mock data while Member 4 builds the engine
- Member 3 can begin graph storage implementation once the schema is known

---

## 8. Daily Working Plan

### Day 1 — Setup and contracts
- Member 1: define schemas and API routes
- Member 2: prepare sample input structures
- Member 3: prepare graph shape expectations
- Member 4: define simulation outputs
- Member 5: define UI pages and sample content

### Day 2 — Build core backend pieces
- Member 2: implement ingestion/parser
- Member 3: implement graph persistence and retrieval
- Member 4: implement simulation and planning logic
- Member 1: wire the backend together and handle errors

### Day 3 — Connect UI and demo flow
- Member 5: build frontend screens and connect to APIs
- Member 1: fix integration issues
- Member 3/4: support with realistic sample data and outputs

### Day 4 — Polish and deploy
- Member 5: create polished demo narrative and UI polish
- Member 1: deploy and verify live environment
- Everyone: test the full user flow

---

## 9. What Each Member Must Finish Before the End

### Member 1
- Final API contract
- Health endpoint
- Upload endpoint working
- Simulation and plan endpoints wired
- Deployment verified

### Member 2
- Parser accepts sample input
- Input is normalized correctly
- Validation works

### Member 3
- Graph can store and return nodes/edges
- Digital twin output is usable by the UI

### Member 4
- Simulation outputs risk and planning results
- Migration waves are generated logically

### Member 5
- UI shows the full flow end-to-end
- Demo pages are polished and presentable

---

## 10. Communication Rules

To avoid confusion, every member should follow these rules:
1. Do not start a new feature without confirming the input/output contract.
2. If you create or change an endpoint shape, update the shared schema first.
3. Commit often and push small changes.
4. Use one shared sample dataset for all testing.
5. Every day, each member should report:
   - what they completed
   - what is blocked
   - what they will do next

---

## 11. What to Prioritize for the Hackathon

If time is short, prioritize these in order:
1. Upload and parse sample data
2. Show graph visualization
3. Show simulation and planning output
4. Show polished dashboard and demo narrative
5. Deployment

This is the minimum winning demo path.

---

## 12. Final Recommendation

The team should not try to build everything perfectly. The winning approach is:
- build the core flow first
- make it look polished
- make it easy to explain
- make it work reliably on a live URL

If the team follows this order, the project will move smoothly and the risk of conflict will stay low.

### 1. GET /api/health
Response:
```json
{
  "status": "healthy",
  "api": "online"
}
```

### 2. POST /api/upload
Input:
- form-data with nodes_file and edges_file OR JSON payload

Response:
```json
{
  "status": "success",
  "parsed_nodes_count": 5,
  "parsed_edges_count": 4,
  "warnings": [],
  "errors": []
}
```

### 3. GET /api/graph
Response:
```json
{
  "nodes": [],
  "edges": []
}
```

### 4. POST /api/simulate
Input:
```json
{
  "target_id": "billing_service",
  "already_migrated": []
}
```

Response:
```json
{
  "target_id": "billing_service",
  "impacted_nodes": [],
  "revenue_at_risk": 120000,
  "total_hosting_cost": 30000,
  "monte_carlo": {}
}
```

### 5. POST /api/plan
Response:
```json
{
  "waves": []
}
```

### 6. POST /api/chat or /api/assistant
Input:
```json
{
  "message": "Estimate migration effort"
}
```

Output:
```json
{
  "reply": "Here is the assessment summary"
}
```

---

## 8. Database and Storage Plan

### Primary store: Neo4j
Use Neo4j for the digital twin and dependency graph.

Recommended node/edge structure:
- Nodes: systems/applications/databases
- Relationships: depends_on, uses_db, calls_api, runs_on

### Metadata store
Use simple metadata storage for assessment context and uploaded files.
For the hackathon, keep this lightweight:
- JSON files for sample data and demo snapshots
- Optional SQLite if needed for quick persistence

Do not introduce Postgres or another heavy database unless the team is already comfortable with it.

### Suggested assessment metadata fields
```json
{
  "assessment_id": "demo-001",
  "customer_name": "ABC Insurance",
  "project_name": "Cloud Migration",
  "target_cloud": "AWS",
  "status": "completed",
  "created_at": "2026-07-24"
}
```

---

## 9. AWS Deployment Plan Under $70

### Recommended deployment path
Use AWS Lightsail or a low-cost EC2 instance.

Best choice:
- 1 Ubuntu Lightsail instance
- Docker installed
- Backend container running on port 8000
- Frontend served via Nginx or static hosting

### Why this is ideal
- Very cheap
- Simple to SSH into
- Easier to demo than a full ECS/Kubernetes setup
- Fits the budget comfortably

### Budget estimate
- Lightsail instance: about $3.50–$10/month depending on size
- Storage: very low
- Logs and bandwidth: low
- Total: likely under $20 for the hackathon period

### Deployment checklist
1. Launch Ubuntu instance
2. Install Docker and Docker Compose
3. Clone the repo
4. Set environment variables
5. Run backend and frontend containers
6. Open the public IP in the browser

### Optional low-cost extras
- S3 bucket for uploaded files if needed
- Route53 not required for the demo
- Use an IP directly for the presentation

---

## 10. Kiro Usage Plan

Kiro should be used as a speed tool, not as the main architecture decision maker.

Use Kiro for:
- Boilerplate generation
- Small helper functions
- Test scaffolding
- Refactoring ideas
- Quick code suggestions when stuck

Do not use Kiro to replace:
- architectural decisions
- API contract agreements
- integration planning
- deployment decisions

---

## 11. Git and Merge Strategy

To avoid merge conflicts:
- Each person works on a dedicated branch
- Do not edit the same file unless necessary
- Commit often and push small changes
- Member 1 reviews all shared backend changes

Suggested branches:
- main
- feature/ingestion
- feature/graph
- feature/simulation
- feature/frontend
- feature/deployment

---

## 12. Risk Plan for the Weak Contributor

Since one person may not contribute consistently:
- Do not assign them to critical backend, agent, or deployment ownership
- Give them non-blocking tasks such as:
  - demo narrative
  - sample data generation
  - UI polish
  - screenshot collection
  - presentation notes
  - QA checklist
  - light documentation

If they do not contribute, the project still works because the critical path is owned by the other four members.

---

## 13. Final Demo Scope

The demo should focus on three strong moments:
1. Upload sample enterprise metadata
2. View the graph and AI-generated assessment summary
3. See migration waves and simulation output

### Demo flow
- Upload sample system metadata
- Show generated digital twin
- Show dependency graph
- Show risk and complexity output
- Show migration waves
- Show deployment URL

This is enough to impress judges without overcomplicating the experience.

---

## 14. Recommended Execution Order for the Team

1. Member 1 defines schemas and API contracts
2. Member 2 builds ingestion and parser normalization
3. Member 3 builds graph loading and digital twin output
4. Member 4 builds simulation and planning logic
5. Member 5 builds the UI around the backend contract
6. Member 1 integrates everything and deploys
7. Everyone helps with demo polish

This order minimizes dependency conflict and keeps progress steady.
