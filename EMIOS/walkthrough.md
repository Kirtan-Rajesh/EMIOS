# Walkthrough & Execution Guide - EMIOS

EMIOS has been designed with a **dual-execution system**. You can run it either in **Zero-Configuration Mode** (using an in-memory graph fallback, requiring only Python) or **Complete Database Mode** (spinning up Neo4j and Qdrant via Docker Compose).

---

## Method 1: Zero-Configuration Mode (Recommended for Quick Test)

This mode runs the entire stack in memory, requiring no database installation or Docker setups. The frontend is automatically served by the FastAPI web server.

### Step 1: Install Dependencies
Open your shell terminal in the repository root and install the dependencies:
```bash
pip install -r backend/requirements.txt
```
*(Since you have `uv` installing, you can also run `uv pip install -r backend/requirements.txt` for speed)*

### Step 2: Run the Server
Start the backend FastAPI server:
```bash
cd backend
python main.py
```
*The server will start on `http://localhost:8000` and output: `Could not connect to Neo4j/Qdrant. Graph features will run in mock/local-fallback mode.`*

### Step 3: Test in the Browser
Open your browser and navigate to:
👉 **[http://localhost:8000](http://localhost:8000)**

---

## Method 2: Complete Mode (With Graph Databases)

This mode connects the Living Digital Twin to a live Neo4j Graph Database and Qdrant Vector Store.

### Step 1: Start Databases
Ensure Docker Desktop is running, and spin up the databases:
```bash
docker compose up -d
```
*(This starts Neo4j on port 7474/7687 and Qdrant on port 6333)*

### Step 2: Run the Server
Launch the backend server:
```bash
cd backend
python main.py
```
*The server will detect the databases and log: `Successfully connected to Neo4j database` & `Successfully connected to Qdrant vector database`.*

### Step 3: Test in the Browser
Open your browser and navigate to:
👉 **[http://localhost:8000](http://localhost:8000)**

---

## Interactive E2E Walkthrough Scenarios

Once the browser opens `http://localhost:8000`, follow this interactive demo scenario to test all features:

### 1. Load the Digital Twin
- Click the **Reset & Load Demo** button in the top right.
- You will see the **Living Digital Twin** visual force-directed graph render instantly in the center. 
- You can hover over services, zoom/pan, and select service nodes (e.g., clicking on **Legacy Core Monolith**).

### 2. Run a What-If Risk Simulation
- Click on the **Authentication Database** node. The right panel will inspect its metadata.
- Click **Simulate Migration Risk**.
- The UI will automatically switch to the **What-If Simulation** tab:
  - **Cascading Path**: Visually outlines risk propagation (e.g. databases going offline cascades risk to microservices and gateways).
  - **Impact Summary**: Shows the calculated **Revenue-At-Risk** (sum of impacted system revenue multiplied by propagation risk probability).
  - **Monte Carlo Forecast**: Switch to this sub-tab to see a probability chart (S-Curve) displaying the 10%, 50%, and 90% confidence bands of expected cost and duration.

### 3. Orchestrate Multi-Agent Wave Planning
- Click the **Run Multi-Agent Planner** button in the top header.
- The UI switches to the **Agentic Wave Planner** tab:
  - **Multi-Agent Dialogue Logs**: See the live conversation transcripts of the agents negotiating (e.g., Discovery Agent flagging orphans, Dependency Agent spotting loops, Risk Agent objecting to high risks, and Planner Agent reorganizing waves).
  - **Generated Waves**: Displays the final sequenced migration waves (Wave 1, Wave 2, Wave 3...) with individual service risk cards.
  - **Decoupling Actions**: Recommends modernization architectures (e.g., suggesting queue decouplers for circular dependency loops).

### 4. Ingest Raw JSON Metadata (V2 Value Quantification)
- Click the **Upload CSV** button in the top header.
- Open [Sample_Input.json](file:///e:/POC_Projects/EMIOS/Sample_Input.json) in your editor, copy the entire JSON array, and paste it into the **Systems Metadata (Nodes CSV)** text box (leave the bottom Dependencies box empty).
- Click **Submit & Build Graph**.
- **Digital Twin map auto-generation**: EMIOS dynamically detects the JSON dump format, parses `PaymentService` and `AuthService`, establishes the dependencies, and updates the graph visualization instantly.
- **Node details**: Click on `PaymentService` to view its specific **Runtime** (`Java 17`) and **Annual Hosting Cost** (`$45,000/yr`) in the Node Inspector.
- **Value Quantification**: Run a What-If simulation on `PaymentService` and view the sidebar to see the parsed **Total Annual Hosting Cost** and the calculated **Potential Cloud Savings (Est. 30%)** (V2 Success Criterion 5).

---

## Automated Algorithms Verification

We have validated the core business logic algorithms (downstream cascading pathfinder, Monte Carlo distributions, and multi-agent LangGraph sequencer) in a test harness.

Test execution output:
```text
Testing Simulation & Agentic Planning Algorithms...
Loaded 8 nodes and 10 edges from Demo Dataset.

Running cascading failure simulation for 'auth_db'...
Total Revenue At Risk: $260,400.00
Cascading Paths found:
  - auth_db -> monolith
  - auth_db -> auth_service
Simulation: SUCCESS

Running Monte Carlo simulation...
Expected Duration: 275.2 days
Expected Cost: $659,681.67
Monte Carlo: SUCCESS

Running Multi-Agent Wave Planning Negotiation...
Negotiation Waves:
  Wave 1: ['auth_db', 'payment_gateway', 'inventory_db', 'shared_event_bus']
  Wave 2: ['inventory_service', 'analytics_worker', 'monolith', 'auth_service']

Decoupling Mitigations Projections:
  - Cycle: ['monolith', 'auth_service'] -> Recommendation: Decouple dependency from 'auth_service' to 'monolith' by introducing a message broker/queue or abstracting to an event-driven interface.
Multi-Agent Planning: SUCCESS

Testing raw JSON component-level ingestion (Sample_Input.json)...
Parsed 2 nodes and 3 edges.
Ingestion verification: SUCCESS

All algorithms and JSON parsing verified successfully!
```
