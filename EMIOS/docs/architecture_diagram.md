# System Architecture & Component Design - EMIOS

This document presents the complete system architecture for **EMIOS** (*Enterprise Migration Intelligence Operating System*). It details every layer, component, data flow, background service, database storage model, and fallback mechanism across the application.

---

## 1. High-Level Architecture Overview

EMIOS is structured into **5 clean architectural tiers**: Presentation, Gateway & Middleware, API Routes, Processing Subsystems, and Hybrid Storage.

```mermaid
graph TD
    subgraph Tier1 ["Tier 1: Presentation Layer (Frontend SPA)"]
        UI["React 18 Single Page Application"]
        subgraph Visuals ["UI Components & Canvas"]
            VisJS["Vis.js Force Graph Engine"]
            MUI["Material UI v5 Theme System"]
            Recharts["Recharts Analytics Dashboard"]
        end
        UI --- Visuals
    end

    subgraph Tier2 ["Tier 2: Gateway & Middleware Layer (FastAPI)"]
        Server["Uvicorn ASGI Web Server"]
        subgraph Middleware ["Cross-Cutting Middleware"]
            CORS["CORS Middleware"]
            Telemetry["Latency & Request Logging"]
            ExcHandler["EMIOSException Handler"]
        end
        Server --- Middleware
    end

    subgraph Tier3 ["Tier 3: Application API Router (/api)"]
        Endpoints["REST API Endpoints (/graph, /reset, /upload, /simulate, /plan, /health, /templates)"]
    end

    subgraph Tier4 ["Tier 4: Core Processing & Intelligence Subsystems"]
        subgraph Ingestion ["Ingestion Subsystem"]
            IngestProc["DictReader CSV & JSON Mappers"]
            IngestVal["Validation & Report Engine"]
            IngestProc --> IngestVal
        end

        subgraph SimEngine ["Simulation Subsystem"]
            Cascade["Cascading Risk Pathfinder"]
            MonteCarlo["Monte Carlo Simulator (1000 trials)"]
            Cascade --> MonteCarlo
        end

        subgraph AgentEngine ["LangGraph Multi-Agent Planner"]
            Agents["4 Negotiating Agents (Discovery, Dependency, Risk, Planner)"]
            State["AgentState Memory Store"]
            Agents <--> State
        end
    end

    subgraph Tier5 ["Tier 5: Hybrid Storage & Persistence Layer"]
        subgraph StorageSelector ["Graph Service Router (neo4j_service.py)"]
            Neo4j["Neo4j Graph Database (Production / Docker)"]
            Qdrant["Qdrant Vector DB (Embeddings / Docker)"]
            InMemoryDB["InMemoryGraphStore (Zero-Config Fallback)"]
        end
    end

    %% Clean Tier-to-Tier Linear Connections
    UI -->|HTTP / REST JSON| Server
    Server --> Endpoints
    
    Endpoints -->|Upload Payload| Ingestion
    Endpoints -->|Simulation Request| SimEngine
    Endpoints -->|Orchestrate Waves| AgentEngine
    Endpoints -->|Graph Queries & Resets| StorageSelector

    Ingestion --> StorageSelector
    SimEngine --> StorageSelector
    AgentEngine --> StorageSelector
```

---

## 2. End-to-End Ingestion Flow

The sequence diagram below details how raw CSV files or JSON metadata payloads are validated, parsed, and mapped into the Living Digital Twin database graph.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Frontend as SPA Frontend (index.html)
    participant Endpoint as REST API (/api/upload)
    participant Resolver as Schema Resolver (resolve_key)
    participant Validator as Validation Engine
    participant GraphStore as Graph Service (neo4j_service.py)
    participant Database as Neo4j DB / InMemoryGraphStore

    User->>Frontend: Paste CSV/JSON or Upload Files
    Frontend->>Endpoint: POST /api/upload (FormData or JSON body)
    
    alt JSON Upload
        Endpoint->>Validator: Validate component_id, cost, and dependencies
    else CSV Upload
        Endpoint->>Resolver: Resolve flexible headers (System ID, App ID, Priority, Revenue, Cost)
        Endpoint->>Validator: Check required fields (id, name)
    end

    Validator->>Validator: Check for duplicate System IDs
    Validator->>Validator: Validate edge targets exist in node set
    Validator->>Validator: Detect self-referential loops (source == target)
    Validator-->>Endpoint: Return cleaned Node & Edge sets + Warnings/Errors list

    Endpoint->>GraphStore: reset_and_populate_graph(nodes, edges)
    
    alt Neo4j Driver Active
        GraphStore->>Database: MATCH (n) DETACH DELETE n; CREATE (s:Service); CREATE (a)-[:DEPENDS_ON]->(b)
    else Neo4j Unavailable / Zero-Config
        GraphStore->>Database: in_memory_db.clear(); populate nodes & edges
    end

    Endpoint-->>Frontend: UploadResponse (status, parsed_nodes, parsed_edges, skipped_count, warnings, errors)
    Frontend->>User: Display Ingestion Report Dialog & Render vis.js Graph
```

---

## 3. Multi-Agent Orchestration Loop (LangGraph Workflow)

When the user triggers **"Run Multi-Agent Planner"**, the execution flow transitions into a stateful multi-agent dialogue orchestrated by LangGraph.

```mermaid
stateDiagram-v2
    [*] --> DiscoveryAgent: Start Planning Request

    state DiscoveryAgent {
        [*] --> CheckOrphans: Scan for disconnected nodes
        CheckOrphans --> CheckSharedDB: Identify DBs accessed by multiple services
        CheckSharedDB --> LogDiscovery: Log report into AgentState
    }

    DiscoveryAgent --> DependencyAgent: Pass AgentState

    state DependencyAgent {
        [*] --> BuildNetworkX: Construct DiGraph
        BuildNetworkX --> FindCycles: Execute simple_cycles algorithm
        FindCycles --> ProposeDecoupling: Formulate queue/event-driven decoupling strategies
    }

    DependencyAgent --> RiskAgent: Pass AgentState

    state RiskAgent {
        [*] --> EvaluateFailureProb: Compute risk score per component
        EvaluateFailureProb --> FlagHighRisk: Object to high-risk migrations in early waves
    }

    RiskAgent --> PlannerAgent: Pass AgentState

    state PlannerAgent {
        [*] --> TopologicalSort: Run kahn/topological sequence on DAG
        TopologicalSort --> ResolveObjections: Adjust waves for Risk Agent objections
        ResolveObjections --> FormulateRoadmap: Generate Wave 1, Wave 2... Wave N
    }

    PlannerAgent --> ConditionCheck: Iteration Count Check

    state ConditionCheck <<choice>>
    ConditionCheck --> DiscoveryAgent: If Objections Unresolved & Iterations < Max (Re-negotiate)
    ConditionCheck --> Finished: Iterations Complete or Consensus Reached

    Finished --> [*]: Return PlanningResponse (waves, decoupling_strategies, negotiation_logs)
```

---

## 4. Cascading Risk Simulation & Monte Carlo Architecture

The simulation engine combines graph propagation analysis with statistical modeling:

```mermaid
flowchart LR
    subgraph Trigger
        Req["POST /api/simulate (target_id, already_migrated)"]
    end

    subgraph CascadingFailureEngine ["Cascading Failure Engine (simulation_engine.py)"]
        BFS["BFS Downstream Pathfinder"]
        ProbCalc["Attenuated Risk Probability Calculation"]
        RevCalc["Revenue-at-Risk Accumulator"]
    end

    subgraph MonteCarloEngine ["Monte Carlo Engine"]
        Sampling["1,000 Iteration Trial Generator"]
        DistCalc["Duration & Cost Variance Sampling"]
        Percentiles["Compute 10th, 50th, 90th Percentiles & S-Curve"]
    end

    subgraph ResponsePayload ["SimulationResponse Payload"]
        Out1["impacted_services: List[ServiceNode]"]
        Out2["critical_paths: List[List[str]]"]
        Out3["revenue_at_risk: Float ($/mo)"]
        Out4["monte_carlo: Percentile Distribution"]
    end

    Req --> BFS
    BFS --> ProbCalc
    ProbCalc --> RevCalc
    ProbCalc --> Sampling
    Sampling --> DistCalc
    DistCalc --> Percentiles
    
    RevCalc --> Out3
    BFS --> Out2
    ProbCalc --> Out1
    Percentiles --> Out4
```

---

## 5. Granular Subsystem & Module Index

| Component Layer | File Path / Module | Key Functions / Classes | Responsibility & Purpose |
| :--- | :--- | :--- | :--- |
| **Server Gateway** | [main.py](file:///e:/POC_Projects/EMIOS/backend/main.py) | `FastAPI`, `log_latency_middleware`, `emios_exception_handler` | Application entry point, ASGI server initialization, static file serving, CORS setup, latency telemetry, and unified exception mapping. |
| **API Endpoints** | [endpoints.py](file:///e:/POC_Projects/EMIOS/backend/app/api/endpoints.py) | `fetch_graph`, `reset_graph`, `upload_metadata`, `download_templates`, `simulate_migration`, `plan_migration` | Exposes REST endpoints for digital twin retrieval, database resets, CSV/JSON metadata ingestion, sample template downloads, simulations, and agent workflows. |
| **Graph Database Service** | [neo4j_service.py](file:///e:/POC_Projects/EMIOS/backend/app/services/neo4j_service.py) | `InMemoryGraphStore`, `get_demo_dataset`, `reset_and_populate_graph`, `get_graph` | Hybrid database abstraction layer managing Neo4j connections and providing transparent in-memory fallback execution. |
| **Simulation Core** | [simulation_engine.py](file:///e:/POC_Projects/EMIOS/backend/app/services/simulation_engine.py) | `run_cascading_failure`, `run_monte_carlo` | Downstream risk pathfinder computing revenue-at-risk propagation and running 1,000 Monte Carlo distribution trials. |
| **LangGraph Workflow** | [workflow.py](file:///e:/POC_Projects/EMIOS/backend/app/agents/workflow.py) | `discovery_agent`, `dependency_agent`, `risk_agent`, `planner_agent`, `run_agent_negotiation` | Stateful multi-agent orchestrator executing negotiation rounds between 4 specialized AI agents. |
| **Agent State Model** | [state.py](file:///e:/POC_Projects/EMIOS/backend/app/agents/state.py) | `AgentState` | Typed dictionary state schema holding services, dependencies, negotiation logs, and wave roadmaps. |
| **Configuration Schema** | [config.py](file:///e:/POC_Projects/EMIOS/backend/app/core/config.py) | `Settings` | Pydantic configuration schema reading environment variables (`NEO4J_URI`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, etc.). |
| **Database Connector** | [db.py](file:///e:/POC_Projects/EMIOS/backend/app/core/db.py) | `init_db`, `close_db`, `neo4j_driver` | Neo4j Python driver connection manager with error handling. |
| **Constants Registry** | [constants.py](file:///e:/POC_Projects/EMIOS/backend/app/core/constants.py) | Migration multipliers, thresholds | Centralized domain constants for risk attenuation factors, cost multipliers, and duration estimates. |
| **Exceptions Subsystem** | [exceptions.py](file:///e:/POC_Projects/EMIOS/backend/app/core/exceptions.py) | `EMIOSException`, subclasses | Structured domain exception hierarchy mapping custom exceptions to clean API error JSONs. |
| **Frontend Visualizer** | [index.html](file:///e:/POC_Projects/EMIOS/frontend/index.html) | `App`, vis.js Network, MUI theme, Recharts | Single Page Application presenting interactive force-directed graph twin, risk dashboards, agent conversation logs, and ingestion report dialogs. |
| **Demo Datasets** | [demo_nodes.csv](file:///e:/POC_Projects/EMIOS/backend/app/resources/demo_nodes.csv), [demo_edges.csv](file:///e:/POC_Projects/EMIOS/backend/app/resources/demo_edges.csv) | 56 nodes, 77 edges | Enterprise retail & banking architecture dataset for zero-config demonstration. |
