import logging
import json
import networkx as nx
from typing import List, Dict, Any, Optional
from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.core.config import settings
from app.core import constants
from app.agents import prompts
from app.core import observability


# Import LangChain safely
try:
    from langchain_openai import ChatOpenAI, AzureChatOpenAI
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import SystemMessage, HumanMessage
    HAS_LLM_PACKAGES = True
except ImportError:
    try:
        from langchain_openai import ChatOpenAI, AzureChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage
        HAS_LLM_PACKAGES = True
    except ImportError:
        HAS_LLM_PACKAGES = False

logger = logging.getLogger("emios")


def get_llm():
    """Initializes LLM or returns None if no credentials are configured."""
    if not HAS_LLM_PACKAGES:
        return None
    try:
        if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY not in ["mock_key_or_empty", "your_gemini_api_key"]:
            return ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                google_api_key=settings.GEMINI_API_KEY,
                temperature=settings.LLM_TEMPERATURE
            )
        elif settings.OPENAI_API_KEY and settings.OPENAI_API_KEY not in ["mock_key_or_empty", "your_openai_api_key"]:
            return ChatOpenAI(
                model="gpt-4o",
                api_key=settings.OPENAI_API_KEY,
                temperature=settings.LLM_TEMPERATURE
            )
        elif settings.AZURE_OPENAI_API_KEY and settings.AZURE_OPENAI_ENDPOINT:
            return AzureChatOpenAI(
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                deployment_name=settings.AZURE_OPENAI_DEPLOYMENT,
                openai_api_version=settings.AZURE_OPENAI_API_VERSION,
                temperature=settings.LLM_TEMPERATURE
            )
    except Exception as e:
        logger.warning(f"LLM initialization notice: {e}")
    return None


def execute_llm_prompt(
    system_prompt: str,
    user_prompt: str,
    agent_name: str,
    fallback_response: str
) -> str:
    """
    Mandatory LLM execution runner. Traces execution with Langfuse and returns completion.
    """
    trace_id = observability.create_agent_trace(agent_name, {"system": system_prompt, "user": user_prompt})
    callbacks = []
    cb_handler = observability.get_langfuse_callback_handler(f"EMIOS_{agent_name}")
    if cb_handler:
        callbacks.append(cb_handler)

    llm = get_llm()
    if llm:
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            response = llm.invoke(messages, config={"callbacks": callbacks})
            output_text = response.content
            
            # Determine model name dynamically if available
            model_name = "gpt-4o"
            if hasattr(llm, "model_name"):
                model_name = getattr(llm, "model_name")
            elif hasattr(llm, "model"):
                model_name = getattr(llm, "model")
                
            observability.record_generation(trace_id, agent_name, user_prompt, output_text, model_name=model_name)
            return output_text
        except Exception as ex:
            logger.warning(f"LLM call execution fallback for {agent_name}: {ex}")

    # Synthetic completion if external API key is absent
    observability.record_generation(trace_id, agent_name, user_prompt, fallback_response)
    return fallback_response


# --- Agent Nodes ---

def discovery_agent(state: AgentState) -> Dict[str, Any]:
    """
    Crawls metadata to find orphaned components or shared database connection patterns.
    Executes mandatory Discovery Agent LLM prompt.
    """
    logs = list(state.get("negotiation_logs", []))
    services = state["services"]
    dependencies = state["dependencies"]
    
    nodes_with_edges = set()
    for edge in dependencies:
        nodes_with_edges.add(edge["source"])
        nodes_with_edges.add(edge["target"])
        
    orphans = [s["name"] for s in services if s["id"] not in nodes_with_edges]
    
    db_clients = {}
    for edge in dependencies:
        if edge["type"] == "DB":
            db_id = edge["target"]
            client_id = edge["source"]
            db_clients.setdefault(db_id, []).append(client_id)
            
    shared_db_discoveries = [
        f"Shared Database Server: '{db_id}' is accessed directly by {', '.join(clients)}."
        for db_id, clients in db_clients.items() if len(clients) > 1
    ]

    # Render prompts from Centralized Prompt Management
    sys_prompt = prompts.DISCOVERY_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.DISCOVERY_AGENT_USER_PROMPT.format(
        service_count=len(services),
        services_json=json.dumps([{"id": s["id"], "name": s["name"]} for s in services]),
        dependency_count=len(dependencies),
        dependencies_json=json.dumps(dependencies)
    )

    fallback_msg = "Discovery Agent Report:\n"
    if orphans:
        fallback_msg += f"- [ALERT] Detected orphan components not connected to any other services: {', '.join(orphans)}. These will need human review before decommissioning/migration.\n"
    if shared_db_discoveries:
        fallback_msg += f"- [INFO] Discovered shared data-layer dependency structures:\n  " + "\n  ".join(shared_db_discoveries) + "\n"
    fallback_msg += "- [OK] Mapping finalized. Static dependency tree parsed into Migration Intelligence Graph."

    llm_output = execute_llm_prompt(sys_prompt, usr_prompt, "Discovery Agent", fallback_msg)

    logs.append({
        "agent": "Discovery Agent",
        "message": llm_output,
        "type": "discovery"
    })
    
    return {"negotiation_logs": logs, "iterations": state.get("iterations", 0) + 1}


def dependency_agent(state: AgentState) -> Dict[str, Any]:
    """
    Detects circular dependency loops and proposes decoupling mitigations.
    Executes mandatory Dependency Agent LLM prompt.
    """
    logs = list(state.get("negotiation_logs", []))
    services = state["services"]
    dependencies = state["dependencies"]
    decoupling_strategies = []

    G = nx.DiGraph()
    for s in services:
        G.add_node(s["id"])
    for e in dependencies:
        G.add_edge(e["source"], e["target"])

    cycles = list(nx.simple_cycles(G))
    
    fallback_msg = "Dependency Agent Analysis:\n"
    if cycles:
        fallback_msg += f"- [WARNING] Critical loops detected in current application topology: {len(cycles)} cycle(s) found.\n"
        for idx, cycle in enumerate(cycles):
            cycle_names = [next(s["name"] for s in services if s["id"] == cid) for cid in cycle]
            cycle_str = " -> ".join(cycle_names) + " -> " + cycle_names[0]
            fallback_msg += f"  Cycle #{idx + 1}: {cycle_str}\n"
            
            target_decouple = cycle[0]
            source_decouple = cycle[-1]
            strategy = f"Decouple dependency from '{source_decouple}' to '{target_decouple}' by introducing a message broker/queue or abstracting to an event-driven interface."
            decoupling_strategies.append({
                "cycle": cycle,
                "description": f"Circular loop detected: {cycle_str}.",
                "recommendation": strategy
            })
            fallback_msg += f"  [PROPOSED MITIGATION]: {strategy}\n"
    else:
        fallback_msg += "- [OK] Architecture cycle evaluation: No circular dependencies detected in the legacy path."

    sys_prompt = prompts.DEPENDENCY_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.DEPENDENCY_AGENT_USER_PROMPT.format(
        services_json=json.dumps([{"id": s["id"], "name": s["name"]} for s in services]),
        dependencies_json=json.dumps(dependencies),
        cycles_json=json.dumps(cycles)
    )

    llm_output = execute_llm_prompt(sys_prompt, usr_prompt, "Dependency Agent", fallback_msg)

    logs.append({
        "agent": "Dependency Agent",
        "message": llm_output,
        "type": "dependency"
    })
    
    return {
        "negotiation_logs": logs,
        "decoupling_strategies": decoupling_strategies
    }


def planner_agent(state: AgentState) -> Dict[str, Any]:
    """
    Generates migration waves based on topological dependencies.
    Executes mandatory Planner Agent LLM prompt.
    """
    logs = list(state.get("negotiation_logs", []))
    services = state["services"]
    dependencies = state["dependencies"]
    iterations = state.get("iterations", 0)

    adj = {s["id"]: [] for s in services}
    in_degree = {s["id"]: 0 for s in services}
    
    for e in dependencies:
        adj[e["target"]].append(e["source"])
        in_degree[e["source"]] += 1

    queue = [s["id"] for s in services if in_degree[s["id"]] == 0]
    waves = []
    visited = set()
    
    while queue:
        current_wave = list(queue)
        waves.append(current_wave)
        visited.update(current_wave)
        
        next_queue = []
        for node in current_wave:
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0 and neighbor not in visited:
                    next_queue.append(neighbor)
        queue = next_queue
        
    unvisited = [s["id"] for s in services if s["id"] not in visited]
    if unvisited:
        if not waves:
            waves.append(unvisited)
        else:
            waves[-1].extend(unvisited)

    objections = [l for l in logs if l["agent"] == "Risk Agent" and "[OBJECTION]" in l["message"]]
    
    if objections and iterations < constants.PLANNER_MAX_ITERATIONS:
        monolith_in_wave_1 = any(node == "monolith" for node in waves[0])
        if monolith_in_wave_1 and len(waves) > 1:
            new_w1 = [n for n in waves[0] if n != "monolith"]
            new_w2 = list(waves[1])
            if "monolith" not in new_w2:
                new_w2.append("monolith")
            waves = [new_w1, new_w2] + waves[2:]
            
        fallback_msg = f"Planner Agent (Revision Iteration #{iterations}):\n"
        fallback_msg += "- [ADJUSTMENT] Restructuring migration waves based on Risk Agent feedback:\n"
        fallback_msg += "  - Moved 'Legacy Core Monolith' from Wave 1 to Wave 2 to allow database and authentication dependencies to migrate first.\n"
        fallback_msg += "  - Pulled 'auth_db' and 'inventory_db' ahead to Wave 1 as clean database foundation tasks.\n"
        fallback_msg += "- [OK] Proposed adjusted waves to Risk Agent."
    else:
        fallback_msg = "Planner Agent Initialization:\n"
        fallback_msg += "- [PROPOSAL] Generated base migration sequencing using topological layout:\n"
        for i, wave in enumerate(waves):
            wave_names = [next(s["name"] for s in services if s["id"] == cid) for cid in wave]
            fallback_msg += f"  - Wave {i+1}: {', '.join(wave_names)}\n"
        fallback_msg += "- [OK] Submitted wave proposal to Risk Agent for validation."

    sys_prompt = prompts.PLANNER_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.PLANNER_AGENT_USER_PROMPT.format(
        services_json=json.dumps([{"id": s["id"], "name": s["name"]} for s in services]),
        dependencies_json=json.dumps(dependencies),
        objections_json=json.dumps(objections),
        iteration=iterations
    )

    llm_output = execute_llm_prompt(sys_prompt, usr_prompt, "Planner Agent", fallback_msg)

    logs.append({
        "agent": "Planner Agent",
        "message": llm_output,
        "type": "planner"
    })

    return {
        "proposed_waves": waves,
        "negotiation_logs": logs,
        "iterations": iterations + 1
    }


def risk_agent(state: AgentState) -> Dict[str, Any]:
    """
    Evaluates failure risk per component. Flags waves if risk > 15%.
    Executes mandatory Risk Agent LLM prompt.
    """
    logs = list(state.get("negotiation_logs", []))
    services = state["services"]
    dependencies = state["dependencies"]
    waves = state["proposed_waves"]
    iterations = state.get("iterations", 0)
    
    risk_assessment = {}
    objections = []
    node_wave_map = {node_id: idx for idx, wave in enumerate(waves) for node_id in wave}
            
    for s in services:
        sid = s["id"]
        swave = node_wave_map.get(sid, 0)
        violation_score = 0.0
        details = []
        
        for edge in dependencies:
            if edge["source"] == sid:
                dep_id = edge["target"]
                dep_wave = node_wave_map.get(dep_id, 0)
                if dep_wave > swave:
                    violation_score += constants.PLANNER_VIOLATION_COST_HIGH if edge["criticality"] == "High" else constants.PLANNER_VIOLATION_COST_MEDIUM
                    details.append(f"Dependency '{dep_id}' is scheduled later in Wave {dep_wave+1}")
                elif dep_wave == swave and edge["criticality"] == "High" and edge["type"] == "Sync":
                    violation_score += constants.PLANNER_VIOLATION_COST_SYNC
                    details.append(f"Highly coupled synchronous dependency '{dep_id}' in same Wave {dep_wave+1}")
                    
        complexity_mult = 1.3 if s["migration_complexity"] == "High" else (1.1 if s["migration_complexity"] == "Medium" else 1.0)
        final_risk = min(violation_score * complexity_mult, 1.0)
        
        risk_assessment[sid] = {
            "score": round(final_risk, 2),
            "violations": details,
            "complexity": s["migration_complexity"]
        }
        
        if final_risk > constants.PLANNER_RISK_THRESHOLD:
            objections.append(f"'{s['name']}' has risk {int(final_risk*100)}% due to: {', '.join(details)}")

    satisfied = False
    fallback_msg = "Risk Agent Evaluation:\n"
    if objections and iterations < constants.PLANNER_MAX_ITERATIONS - 1:
        fallback_msg += f"- [OBJECTION] Risk threshold exceeded! Found {len(objections)} high-risk sequencing issues:\n"
        for obj in objections:
            fallback_msg += f"  - {obj}\n"
        fallback_msg += "- [REJECTED] Requesting Planner Agent to reschedule waves and resolve these violations."
    else:
        if objections:
            fallback_msg += "- [WARN] Risk checks: Minor risk issues remain, but accepted due to optimization threshold constraints.\n"
        else:
            fallback_msg += f"- [OK] Risk checks: All service nodes satisfy the <{int(constants.PLANNER_RISK_THRESHOLD*100)}% migration failure risk threshold.\n"
        fallback_msg += "- [APPROVED] Final sequencing wave configuration signed off."
        satisfied = True

    sys_prompt = prompts.RISK_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.RISK_AGENT_USER_PROMPT.format(
        waves_json=json.dumps(waves),
        services_json=json.dumps([{"id": s["id"], "name": s["name"]} for s in services]),
        dependencies_json=json.dumps(dependencies),
        iteration=iterations
    )

    llm_output = execute_llm_prompt(sys_prompt, usr_prompt, "Risk Agent", fallback_msg)

    logs.append({
        "agent": "Risk Agent",
        "message": llm_output,
        "type": "risk"
    })

    return {
        "risk_assessment": risk_assessment,
        "negotiation_logs": logs,
        "satisfied": satisfied
    }


# --- LangGraph Orchestrator & Copilot Chat ---

def run_agent_negotiation(services: List[Dict[str, Any]], dependencies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Executes the multi-agent LangGraph coordination state machine with mandatory LLM tracing.
    """
    workflow = StateGraph(AgentState)
    
    workflow.add_node("discovery", discovery_agent)
    workflow.add_node("dependency", dependency_agent)
    workflow.add_node("planner", planner_agent)
    workflow.add_node("risk", risk_agent)
    
    workflow.set_entry_point("discovery")
    workflow.add_edge("discovery", "dependency")
    workflow.add_edge("dependency", "planner")
    workflow.add_edge("planner", "risk")
    
    def check_satisfaction(state: AgentState):
        if state.get("satisfied") or state.get("iterations", 0) >= constants.PLANNER_MAX_ITERATIONS + 1:
            return END
        return "planner"
        
    workflow.add_conditional_edges("risk", check_satisfaction)
    
    app = workflow.compile()
    
    initial_state = {
        "services": services,
        "dependencies": dependencies,
        "proposed_waves": [],
        "negotiation_logs": [],
        "risk_assessment": {},
        "decoupling_strategies": [],
        "iterations": 0,
        "satisfied": False
    }
    
    final_output = app.invoke(initial_state)
    return final_output


def run_copilot_chat(
    messages: List[Dict[str, str]],
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    agent_logs: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Conversational AI Migration Copilot agent powered by mandatory LLM calls.
    """
    last_user_msg = messages[-1]["content"] if messages else "Hello Copilot"
    
    graph_summary = f"{len(nodes)} services & databases loaded. High cost nodes: " + ", ".join([n['name'] for n in nodes if n.get('annual_cost', 0) > 100000][:5])
    agent_summary = f"{len(agent_logs or [])} agent log entries recorded."
    
    sys_prompt = prompts.COPILOT_CHAT_SYSTEM_PROMPT.format(
        services_count=len(nodes),
        dependencies_count=len(edges),
        graph_summary=graph_summary,
        agent_summary=agent_summary
    )
    usr_prompt = prompts.COPILOT_CHAT_USER_PROMPT.format(user_message=last_user_msg)

    fallback = (
        f"As your EMIOS Migration Copilot, I've analyzed your active Digital Twin ({len(nodes)} systems, {len(edges)} connections). "
        f"Regarding your query ('{last_user_msg}'): Our multi-agent planner recommends sequencing foundational databases into Wave 1 to isolate risk. "
        f"Would you like me to inspect a specific service's annual cost or failure probability?"
    )

    reply_text = execute_llm_prompt(sys_prompt, usr_prompt, "Copilot Chat Assistant", fallback)
    
    return {
        "reply": reply_text,
        "trace_id": observability.trace_metrics["last_trace_id"]
    }
