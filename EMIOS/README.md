# EMIOS — Enterprise Migration Intelligence Operating System

EMIOS is an advanced, intelligence-driven operating system designed to map enterprise application topology landscapes, simulate downstream migration cascading failure risks, quantify cloud cost-savings, and negotiate wave-scheduling roadmaps using cooperative Multi-Agent systems.

---

## Core Capabilities

1. **Enterprise Digital Twin**: An interactive, dynamic topology map displaying legacy environments, systems, runtimes, hosting costs, and connection relationships.
2. **Cascading Failure Simulator**: Real-time evaluation of downstream transitive failure risks when individual target nodes are taken offline/migrated (Breadth-First Pathfinder).
3. **Monte Carlo Cost/Time Estimator**: Probabilistic migration forecast displaying duration and cost ranges under different failure likelihood intervals (Triangular S-Curve sampling).
4. **Value Quantification (V2)**: Real-time projection of monthly revenue-at-risk, overall legacy hosting cost profiles, and potential cloud modernization savings (Est. 30%).
5. **Multi-Agent Wave Planner (LangGraph)**: Specialized AI Agents (Discovery, Dependency, Risk, Planner) that autonomously negotiate sequencing constraints, resolve cycles, and generate a migration wave roadmap.

---

## Technology Stack

* **Backend**: FastAPI, LangGraph, NetworkX, Uvicorn, Python 3.11+
* **Frontend**: React (SPA), Tailwind CSS, Material UI (MUI), Vis.js Network, Recharts
* **Databases**: Neo4j (Graph Twin Store), Qdrant (Vector Policies), In-Memory storage fallback

---

## Local Running Guide

EMIOS includes an automated launcher script (`run_emios.bat`) that handles everything for you (engine checks, container setups, virtual environments, pip dependencies, and server startup).

### Method 1: Quick Automated Launch (Recommended)

Simply double-click or run the launcher script from the root directory:
```powershell
.\run_emios.bat
```

**What the script does automatically**:
1. **Container Engine Setup**: Detects if Docker or Podman is active. Starts the default Podman machine if Podman is found.
2. **Databases Startup**: Starts the database containers (Neo4j on port `7687` and Qdrant on port `6333`) in the background. If no engine is running, it defaults to **Zero-Configuration In-Memory mode**.
3. **Web Browser**: Opens your default browser to the web interface at `http://localhost:8000`.
4. **FastAPI Server**: Checks if the Python virtual environment (`venv`) exists. If missing, it automatically creates it, upgrades pip, installs all dependencies (`backend/requirements.txt`), and starts the FastAPI server.

---

### Method 2: Manual Setup

If you prefer to configure and run the components manually, follow these steps:

#### Step 1: Start Databases (Optional)
Make sure Docker Desktop or Podman Desktop is active, then spin up the backend databases:
```powershell
docker compose up -d
# or: podman compose up -d
```
*Note: If you skip this step, EMIOS will automatically use the mock in-memory fallback database.*

#### Step 2: Create a Virtual Environment
From the project root directory, run:
```powershell
python -m venv venv
```

#### Step 3: Install Requirements
Install the backend requirements inside the virtual environment:
```powershell
.\venv\Scripts\python -m pip install -r backend/requirements.txt
```

#### Step 4: Configure API Keys (Optional)
Create a `.env` file in the `backend/` directory (or copy from `backend/.env.example`). You can supply either an OpenAI API key or a Gemini API key:
```env
# Supply either OpenAI key:
OPENAI_API_KEY=your_openai_api_key

# OR Gemini key:
GEMINI_API_KEY=your_gemini_api_key
```

#### Step 5: Run the Backend Application
Start the Uvicorn web server and API layer:
```powershell
.\venv\Scripts\python backend/main.py
```

#### Step 6: Open in Browser
Open your browser and navigate to:
👉 **[http://localhost:8000](http://localhost:8000)**

---

## Running the Automated Test Suite

We use `pytest` to automatically verify calculation algorithms and API endpoints:
```powershell
$env:PYTHONPATH="backend"
pytest backend/tests
```

---

## Project Structure

```text
EMIOS/
├── backend/
│   ├── app/
│   │   ├── agents/          # LangGraph Multi-Agent workflows & states
│   │   ├── api/             # FastAPI routers & endpoints
│   │   ├── core/            # Configs, exceptions, loggers, constants
│   │   ├── models/          # Pydantic data schemas
│   │   ├── resources/       # Demo CSV node/edge data
│   │   └── services/        # Neo4j graph & simulator services
│   ├── tests/               # Pytest test automation suite
│   ├── Dockerfile           # Multi-stage production container configuration
│   ├── requirements.txt     # Backend library dependencies
│   └── main.py              # Application entry point
├── frontend/
│   ├── index.html           # SPA User Dashboard interface
│   └── index.css            # Stylesheet overrides
├── docker-compose.yml       # Neo4j & Qdrant local composition
├── Sample_Input.json        # Raw component metadata sample
└── walkthrough.md           # Interactive scenario execution walkthrough
```
