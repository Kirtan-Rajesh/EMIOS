import csv
import io
from fastapi import APIRouter, UploadFile, File, Body
from typing import List, Dict, Any, Optional
from app.models.schemas import (
    GraphData, UploadResponse, SimulationRequest, SimulationResponse, PlanningResponse,
    ChatRequest, ChatResponse
)

from app.services.neo4j_service import get_graph, reset_and_populate_graph, get_demo_dataset
from app.services.simulation_engine import run_cascading_failure, run_monte_carlo
from app.agents.workflow import run_agent_negotiation
from app.core import constants
from app.core.exceptions import InvalidIngestionException, SimulationException, WorkflowException, DatabaseConnectionException

router = APIRouter()

@router.get("/graph", response_model=GraphData)
def fetch_graph():
    """
    Returns the current enterprise digital twin nodes and connection relationships.
    """
    try:
        nodes, edges = get_graph()
        return GraphData(nodes=nodes, edges=edges)
    except Exception as e:
        raise DatabaseConnectionException(f"Failed to load digital twin graph: {e}")

@router.post("/reset", response_model=UploadResponse)
def reset_graph():
    """
    Wipes the active database and initializes the default e-commerce legacy system dataset.
    """
    try:
        demo_nodes, demo_edges = get_demo_dataset()
        reset_and_populate_graph(demo_nodes, demo_edges)
        return UploadResponse(
            status="success",
            parsed_nodes_count=len(demo_nodes),
            parsed_edges_count=len(demo_edges),
            message="Successfully loaded legacy e-commerce demonstration dataset."
        )
    except Exception as e:
        raise DatabaseConnectionException(f"Failed to reset database graph: {e}")

def resolve_key(row: Dict[str, Any], possible_keys: List[str], default: Any = None) -> Any:
    # 1. Exact match check
    for k in possible_keys:
        if k in row:
            return row[k]
    # 2. Case-insensitive and trimmed check
    for k in possible_keys:
        normalized_k = k.strip().lower()
        for rk in row.keys():
            if rk.strip().lower() == normalized_k:
                return row[rk]
    return default

@router.get("/templates/download")
def download_templates():
    """
    Returns CSV templates for systems (nodes) and dependencies (edges) to be downloaded by the frontend.
    """
    return {
        "nodes": "System ID,System Name,Category,Priority,Monthly Revenue ($),Complexity,Migration Cost ($),Migration Time (Days),Tech Stack,Annual Hosting Cost ($)\nmonolith,Legacy ERP & Catalog Monolith,Monolith,High,350000.0,High,500000.0,120,COBOL/Java 8,600000.0\nuser_service,Identity & User Access,Microservice,High,180000.0,Medium,35000.0,21,Go 1.20,40000.0\nuser_db,User Profiles Database,Database,High,200000.0,Medium,60000.0,30,PostgreSQL 14,80000.0\norder_service,Order Processing Engine,Microservice,High,300000.0,Medium,45000.0,25,Go 1.20,55000.0\norder_db,Orders Transaction Database,Database,High,300000.0,High,90000.0,45,PostgreSQL 14,120000.0",
        "edges": "From System,To System,Connection Type,Importance\nmonolith,user_service,Sync,High\nuser_service,user_db,DB,High\norder_service,order_db,DB,High\norder_service,user_service,Sync,High"
    }

@router.post("/upload", response_model=UploadResponse)
async def upload_metadata(
    nodes_file: UploadFile = File(None),
    edges_file: UploadFile = File(None),
    json_payload: Optional[GraphData] = Body(None)
):
    """
    Accepts CSV file uploads or JSON payload representing services and dependencies,
    and updates the active Digital Twin in Neo4j. Supports standard database keys
    or human-friendly column names for business analysts. Provides robust validation
    and logs warnings/errors.
    """
    try:
        nodes = []
        edges = []
        warnings = []
        errors = []
        skipped_count = 0
        node_ids = set()

        # Case 1: JSON payload
        if json_payload:
            for n in json_payload.nodes:
                n_dict = n.model_dump()
                if n_dict["id"] in node_ids:
                    warnings.append(f"Duplicate Node ID '{n_dict['id']}' in JSON payload. Overwriting previous entry.")
                nodes.append(n_dict)
                node_ids.add(n_dict["id"])
                
            for e in json_payload.edges:
                e_dict = e.model_dump()
                # Validation checks
                if e_dict["source"] not in node_ids:
                    warnings.append(f"Edge dependency references non-existent source system: '{e_dict['source']}'. Skipping.")
                    skipped_count += 1
                    continue
                if e_dict["target"] not in node_ids:
                    warnings.append(f"Edge dependency references non-existent target system: '{e_dict['target']}'. Skipping.")
                    skipped_count += 1
                    continue
                if e_dict["source"] == e_dict["target"]:
                    warnings.append(f"Self-referential dependency loop detected on system: '{e_dict['source']}'. Skipping.")
                    skipped_count += 1
                    continue
                # Check for duplicate edges
                is_dup = False
                for existing in edges:
                    if existing["source"] == e_dict["source"] and existing["target"] == e_dict["target"]:
                        is_dup = True
                        break
                if is_dup:
                    warnings.append(f"Duplicate dependency edge '{e_dict['source']} -> {e_dict['target']}' detected. Skipping.")
                    skipped_count += 1
                    continue
                edges.append(e_dict)
        
        # Case 2: CSV or JSON file uploaded
        elif nodes_file:
            nodes_content = await nodes_file.read()
            nodes_str = nodes_content.decode("utf-8").strip()
            
            # Check if it is a JSON file (starts with '[')
            if nodes_str.startswith("["):
                import json
                try:
                    raw_list = json.loads(nodes_str)
                    for idx, item in enumerate(raw_list):
                        comp_id = str(item.get("component_id") or "").strip()
                        if not comp_id:
                            errors.append(f"Row {idx+1} in JSON file skipped: missing 'component_id'.")
                            skipped_count += 1
                            continue
                        
                        runtime = str(item.get("runtime") or "Unknown").strip()
                        crit = str(item.get("business_criticality") or "Medium").strip()
                        b_val = "High" if crit.lower() in ["critical", "high"] else ("Medium" if crit.lower() == "medium" else "Low")
                        
                        try:
                            h_cost = float(item.get("annual_hosting_cost") or 0.0)
                        except (ValueError, TypeError):
                            h_cost = 0.0
                            warnings.append(f"Invalid annual hosting cost for '{comp_id}'. Defaulted to $0.0.")
                        
                        node_type = "Database" if "db" in comp_id.lower() or "database" in comp_id.lower() else "Microservice"
                        complexity = "High" if h_cost > 100000 else ("Medium" if h_cost > 20000 else "Low")
                        base_cost = max(h_cost * constants.MIGRATION_COST_FACTOR, constants.MIGRATION_COST_MIN)
                        base_duration = (
                            constants.MIGRATION_DURATION_LOW if complexity == "Low" 
                            else (constants.MIGRATION_DURATION_MEDIUM if complexity == "Medium" 
                            else constants.MIGRATION_DURATION_HIGH)
                        )
                        revenue_impact = round((h_cost * constants.REVENUE_MULTIPLIER) / constants.MONTHS_IN_YEAR, 2)
                        
                        if comp_id in node_ids:
                            warnings.append(f"Duplicate Node ID '{comp_id}' in JSON file. Overwriting previous entry.")
                            # Remove existing node
                            nodes = [n for n in nodes if n["id"] != comp_id]
                            
                        nodes.append({
                            "id": comp_id,
                            "name": comp_id.replace("Service", " Service").replace("DB", " Database").strip(),
                            "type": node_type,
                            "business_value": b_val,
                            "revenue_impact": revenue_impact,
                            "migration_complexity": complexity,
                            "base_cost": base_cost,
                            "base_duration": base_duration,
                            "status": "Legacy",
                            "failure_probability": 0.0,
                            "runtime": runtime,
                            "annual_cost": h_cost
                        })
                        node_ids.add(comp_id)
                        
                        deps = item.get("downstream_dependencies") or []
                        for dep in deps:
                            dep_str = str(dep).strip()
                            if not dep_str:
                                continue
                            edges.append({
                                "source": comp_id,
                                "target": dep_str,
                                "type": "DB" if "db" in dep_str.lower() else "Sync",
                                "criticality": "High" if b_val == "High" else "Medium",
                                "is_discovered": False
                            })
                    
                    # Validate JSON-parsed dependencies references
                    valid_edges = []
                    for e in edges:
                        if e["target"] not in node_ids:
                            warnings.append(f"Dependency references non-existent target: '{e['target']}'. Skipping.")
                            skipped_count += 1
                            continue
                        if e["source"] == e["target"]:
                            warnings.append(f"Self-referential dependency loop detected: '{e['source']}'. Skipping.")
                            skipped_count += 1
                            continue
                        valid_edges.append(e)
                    edges = valid_edges
                    
                except Exception as json_err:
                    raise InvalidIngestionException(f"Failed to parse uploaded JSON file: {json_err}")
            
            else:
                # Parse as CSV
                reader = csv.DictReader(io.StringIO(nodes_str))
                
                # Case-insensitive header checks
                fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
                id_possible = {"id", "system id", "app id", "systemid", "appid", "systemcode", "system code"}
                name_possible = {"name", "system name", "appname", "app name"}
                
                has_id = any(p in fieldnames for p in id_possible)
                has_name = any(p in fieldnames for p in name_possible)
                
                if not has_id or not has_name:
                    raise InvalidIngestionException(
                        "Nodes CSV must contain a System ID (or 'id') and a System Name (or 'name') column."
                    )
                
                # Fill missing column defaults dynamically
                for idx, row in enumerate(reader):
                    row_id = str(resolve_key(row, ["id", "System ID", "App ID", "SystemCode", "System Code"]) or "").strip()
                    row_name = str(resolve_key(row, ["name", "System Name", "Name"]) or "").strip()
                    
                    if not row_id or not row_name:
                        errors.append(f"Nodes CSV row {idx+1} skipped: System ID and Name must be present.")
                        skipped_count += 1
                        continue
                        
                    # Handle duplicate node IDs
                    if row_id in node_ids:
                        warnings.append(f"Duplicate Node ID '{row_id}' in Nodes CSV. Overwriting previous entry.")
                        nodes = [n for n in nodes if n["id"] != row_id]
                    
                    # Convert priority values to business value (High/Medium/Low)
                    raw_b_val = str(resolve_key(row, ["business_value", "Business Value", "Priority"], "Medium")).strip()
                    if raw_b_val.lower() in ["critical", "high", "p1", "p2"]:
                        b_val = "High"
                    elif raw_b_val.lower() in ["medium", "p3"]:
                        b_val = "Medium"
                    else:
                        b_val = "Low"
                        
                    # Safely parse numeric fields
                    try:
                        rev_impact = float(resolve_key(row, ["revenue_impact", "Monthly Revenue ($)", "Monthly Revenue", "Revenue"], 0.0) or 0.0)
                    except (ValueError, TypeError):
                        rev_impact = 0.0
                        warnings.append(f"System '{row_id}': Invalid revenue value. Defaulted to $0.0.")
                        
                    try:
                        base_cost = float(resolve_key(row, ["base_cost", "Migration Cost ($)", "Migration Cost", "Cost"], 10000.0) or 10000.0)
                    except (ValueError, TypeError):
                        base_cost = 10000.0
                        warnings.append(f"System '{row_id}': Invalid migration cost. Defaulted to $10,000.00.")
                        
                    try:
                        base_duration = int(resolve_key(row, ["base_duration", "Migration Time (Days)", "Migration Time", "Time", "Duration"], 14) or 14)
                    except (ValueError, TypeError):
                        base_duration = 14
                        warnings.append(f"System '{row_id}': Invalid migration duration. Defaulted to 14 days.")
                        
                    try:
                        annual_cost = float(resolve_key(row, ["annual_cost", "Annual Cost ($)", "Annual Cost", "Annual Hosting Cost", "Hosting Cost"], 0.0) or 0.0)
                    except (ValueError, TypeError):
                        annual_cost = 0.0
                        warnings.append(f"System '{row_id}': Invalid annual cost. Defaulted to $0.0.")
                        
                    nodes.append({
                        "id": row_id,
                        "name": row_name,
                        "type": str(resolve_key(row, ["type", "Type", "Category"], "Microservice")).strip(),
                        "business_value": b_val,
                        "revenue_impact": rev_impact,
                        "migration_complexity": str(resolve_key(row, ["migration_complexity", "Complexity", "Migration Complexity"], "Medium")).strip(),
                        "base_cost": base_cost,
                        "base_duration": base_duration,
                        "status": "Legacy",
                        "failure_probability": 0.0,
                        "runtime": str(resolve_key(row, ["runtime", "Runtime", "Tech Stack", "Language"], "Unknown")).strip(),
                        "annual_cost": annual_cost
                    })
                    node_ids.add(row_id)

                if edges_file:
                    # Parse edges CSV
                    edges_content = await edges_file.read()
                    edges_str = edges_content.decode("utf-8")
                    reader_edges = csv.DictReader(io.StringIO(edges_str))
                    
                    fieldnames_edges = [f.strip().lower() for f in (reader_edges.fieldnames or [])]
                    source_possible = {"source", "from system", "fromsystem", "client"}
                    target_possible = {"target", "to system", "tosystem", "dependency"}
                    
                    has_source = any(p in fieldnames_edges for p in source_possible)
                    has_target = any(p in fieldnames_edges for p in target_possible)
                    
                    if not has_source or not has_target:
                        raise InvalidIngestionException(
                            "Edges CSV must contain a From System (or 'source') and a To System (or 'target') column."
                        )
                    
                    for idx, row in enumerate(reader_edges):
                        src = str(resolve_key(row, ["source", "From System", "Source", "Client"]) or "").strip()
                        tgt = str(resolve_key(row, ["target", "To System", "Target", "Dependency"]) or "").strip()
                        
                        if not src or not tgt:
                            errors.append(f"Edges CSV row {idx+1} skipped: source and target are required.")
                            skipped_count += 1
                            continue
                            
                        # Validate if systems exist
                        if src not in node_ids:
                            warnings.append(f"Connection skipped: source system '{src}' does not exist in nodes CSV.")
                            skipped_count += 1
                            continue
                        if tgt not in node_ids:
                            warnings.append(f"Connection skipped: target system '{tgt}' does not exist in nodes CSV.")
                            skipped_count += 1
                            continue
                        if src == tgt:
                            warnings.append(f"Self-referential connection skipped on system '{src}'.")
                            skipped_count += 1
                            continue
                            
                        # Check duplicate edge
                        is_dup = False
                        for existing in edges:
                            if existing["source"] == src and existing["target"] == tgt:
                                is_dup = True
                                break
                        if is_dup:
                            warnings.append(f"Duplicate dependency edge '{src} -> {tgt}' detected. Skipping.")
                            skipped_count += 1
                            continue
                            
                        edges.append({
                            "source": src,
                            "target": tgt,
                            "type": str(resolve_key(row, ["type", "Type", "Connection Type"], "Sync")).strip(),
                            "criticality": str(resolve_key(row, ["criticality", "Criticality", "Importance"], "Medium")).strip(),
                            "is_discovered": str(resolve_key(row, ["is_discovered", "Discovered"], "")).lower() == 'true'
                        })
        else:
            raise InvalidIngestionException("Either JSON payload or CSV files must be provided.")

        reset_and_populate_graph(nodes, edges)
        
        status_str = "success"
        if errors:
            status_str = "partial_success" if nodes else "failed"

        return UploadResponse(
            status=status_str,
            parsed_nodes_count=len(nodes),
            parsed_edges_count=len(edges),
            skipped_count=skipped_count,
            warnings=warnings,
            errors=errors,
            message="Metadata processed and digital twin graph database initialized successfully."
        )
    except Exception as e:
        raise InvalidIngestionException(f"Failed to process uploaded metadata: {e}")

@router.post("/simulate", response_model=SimulationResponse)
def simulate_migration(request: SimulationRequest):
    """
    Calculates downstream risk propagation and runs Monte Carlo timeline simulation
    when migrating a specific service node.
    """
    try:
        nodes, edges = get_graph()
        
        # Run risk analysis
        impacted_nodes, critical_paths, revenue_at_risk = run_cascading_failure(
            nodes=nodes,
            edges=edges,
            target_id=request.target_id,
            already_migrated=request.already_migrated
        )
        
        # Run Monte Carlo
        monte_carlo_res = run_monte_carlo(nodes, impacted_nodes)
        
        # Count impacted services
        impacted_count = sum(1 for n in impacted_nodes if n.failure_probability > 0.0 and n.id != request.target_id)
        
        # Calculate financials
        tot_cost = sum(n.annual_cost for n in nodes)
        pot_savings = tot_cost * constants.CLOUD_SAVINGS_MULTIPLIER # Standard savings estimation
        
        return SimulationResponse(
            impacted_services=impacted_nodes,
            critical_paths=critical_paths,
            revenue_at_risk=revenue_at_risk,
            total_impacted_services=impacted_count,
            monte_carlo=monte_carlo_res,
            total_hosting_cost=round(tot_cost, 2),
            potential_savings=round(pot_savings, 2)
        )
    except Exception as e:
        raise SimulationException(f"Simulation failed: {e}")

@router.post("/plan", response_model=PlanningResponse)
def plan_migration():
    """
    Orchestrates the multi-agent LangGraph engine to evaluate architecture constraints,
    resolve circular reference cycles, negotiate wave risks, and design the final roadmap.
    """
    try:
        nodes, edges = get_graph()
        
        # Convert schemas to dicts for state model
        nodes_dict = [n.model_dump() for n in nodes]
        edges_dict = [e.model_dump() for e in edges]
        
        # Run state machine
        negotiation_res = run_agent_negotiation(nodes_dict, edges_dict)
        
        from app.core import observability
        obs_status = observability.get_observability_status()
        
        return PlanningResponse(
            waves=negotiation_res["proposed_waves"],
            decoupling_strategies=negotiation_res["decoupling_strategies"],
            negotiation_logs=negotiation_res["negotiation_logs"],
            risk_assessment=negotiation_res["risk_assessment"],
            trace_id=obs_status["metrics"].get("last_trace_id"),
            observability_summary=obs_status
        )
    except Exception as e:
        raise WorkflowException(f"Planning orchestration failed: {e}")

@router.post("/chat", response_model=ChatResponse)
def copilot_chat(request: ChatRequest):
    """
    Interactive AI Migration Copilot chat endpoint for enterprise architecture discussions.
    """
    try:
        from app.agents.workflow import run_copilot_chat
        nodes, edges = get_graph()
        nodes_dict = [n.model_dump() for n in nodes]
        edges_dict = [e.model_dump() for e in edges]
        messages_dict = [m.model_dump() for m in request.messages]
        
        res = run_copilot_chat(messages_dict, nodes_dict, edges_dict)
        return ChatResponse(
            reply=res["reply"],
            trace_id=res.get("trace_id")
        )
    except Exception as e:
        raise WorkflowException(f"Copilot chat failed: {e}")

@router.get("/observability/status")
def get_observability():
    """
    Exposes self-hosted/cloud Langfuse tracing status and LLM execution metrics.
    """
    from app.core import observability
    return observability.get_observability_status()


@router.get("/health")
def health_check():
    """
    Performs readiness/liveness checks, validating database connectivity.
    """
    from app.services.neo4j_service import neo4j_driver
    db_status = "unconnected"
    if neo4j_driver:
        try:
            with neo4j_driver.session() as session:
                session.run("RETURN 1")
            db_status = "connected"
        except Exception:
            db_status = "offline"
            
    return {
        "status": "healthy" if db_status in ["connected", "unconnected"] else "degraded",
        "database": db_status,
        "api": "online"
    }

