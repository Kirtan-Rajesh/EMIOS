import logging
import json
import re
from datetime import datetime, timezone
import networkx as nx
from typing import List, Dict, Any, Optional
from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.core.config import settings
from app.core import constants
from app.agents import prompts
from app.agents import response_formatter
from app.agents import tools as agent_tools
from app.core import observability
from app.core.llm_provider import invoke_agentic, invoke_with_fallback
from app.models.schemas import ServiceNode
from app.services.simulation_engine import run_monte_carlo

logger = logging.getLogger("emios")


def execute_llm_prompt(
    system_prompt: str,
    user_prompt: str,
    agent_name: str,
    fallback_response: str,
    assessment_id: str = "",
) -> str:
    """
    Mandatory LLM execution runner for the agent pipeline - thin wrapper around
    app.core.llm_provider.invoke_with_fallback() (shared with non-agent LLM call
    sites, e.g. app/services_v1/report_service.py's final migration-plan step).
    `assessment_id`, when the caller has one (every node here reads it off
    `state["assessment_id"]`), groups this call under that assessment's single
    Langfuse trace, inside its "Agent Flow" sub-trace - see
    app.core.observability.create_agent_trace()'s docstring.
    """
    return invoke_with_fallback(system_prompt, user_prompt, agent_name, fallback_response, assessment_id=assessment_id, trace_phase="agent")


def _log_source(raw_output: str, fallback_msg: str) -> str:
    """Whether a node's LLM call actually got a real model response or fell
    through to the deterministic fallback text - invoke_with_fallback()/
    invoke_agentic() (app/core/llm_provider.py) never raise, so the two are
    otherwise indistinguishable to callers; comparing the raw output against
    the exact fallback string this node built is cheaper and less invasive
    than changing those functions' return type. Surfaced in each
    negotiation-log entry so PlannerPage's AgentExplainer can badge fallback
    stages instead of presenting them identically to real output."""
    return "fallback" if raw_output == fallback_msg else "llm"


def _narrative_from_llm_output(llm_output: str) -> str:
    """Every agent system prompt (app/agents/prompts.py) asks the model for a
    strict JSON envelope whose "agent_log" field is explicitly described as
    the "Formatted narrative log for human architects" - but nothing ever
    extracted that field, so whenever a real LLM call actually succeeded
    (as opposed to falling through to the plain-text deterministic
    `fallback_msg` each node builds), the raw JSON envelope itself became
    this stage's displayed negotiation-log message - e.g. a Discovery Agent
    entry showing up as `{"summary": ..., "orphans_found": [...], ...}`
    instead of readable prose. This is why the UI only *sometimes* showed raw
    JSON: exactly whenever a configured LLM provider responded, vs. readable
    text whenever none did and the deterministic fallback took over.

    Extracts "agent_log" when the output parses as the expected JSON shape
    (defensively stripping a ```json code fence some models add despite being
    told not to); returns the input unchanged for anything else (the
    deterministic fallback text, or a model that ignored the JSON
    instruction and replied in plain prose) - never raises.
    """
    text = llm_output.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.strip()
    if not text.startswith("{"):
        return _normalize_to_markdown(llm_output)
    try:
        parsed = json.loads(text)
        agent_log = parsed.get("agent_log") if isinstance(parsed, dict) else None
        if isinstance(agent_log, str) and agent_log.strip():
            return _normalize_to_markdown(agent_log)
    except (json.JSONDecodeError, ValueError):
        pass
    # The full envelope can fail to parse even when "agent_log" itself is
    # perfectly well-formed - observed directly: a model emitting one
    # malformed sibling field (e.g. an unquoted "key": value pair typo'd
    # into a JSON array meant to hold only strings) fails json.loads() for
    # the whole object, which previously meant discarding a good narrative
    # and falling through to dumping the raw (still-broken) JSON text into
    # the UI instead. Recover "agent_log" directly via regex before giving
    # up - the field is usually intact on its own even when a neighbor isn't.
    match = _AGENT_LOG_FIELD_RE.search(text)
    if match:
        try:
            agent_log = json.loads(f'"{match.group(1)}"')
            if isinstance(agent_log, str) and agent_log.strip():
                return _normalize_to_markdown(agent_log)
        except (json.JSONDecodeError, ValueError):
            pass
    return _normalize_to_markdown(llm_output)


# Matches the "agent_log" field's string value directly out of raw (possibly
# invalid-as-a-whole) JSON text - see _narrative_from_llm_output's fallback.
_AGENT_LOG_FIELD_RE = re.compile(r'"agent_log"\s*:\s*"((?:\\.|[^"\\])*)"')

# "=== EMIOS DISCOVERY AGENT LOG ===" / "=== END LOG ===" style banners - the
# UI card these render into already shows the agent's name and status via its
# own header (see AgentExplainer in frontend/src/pages/PlannerPage.tsx), so a
# banner repeating that inside the narrative is pure redundant clutter.
_BANNER_LINE_RE = re.compile(r"^[ \t]*={3,}[^\n]*?={3,}[ \t]*", re.MULTILINE)
# A "•" (or similar Unicode bullet) at the start of a line - not real Markdown
# list syntax, so react-markdown renders it as a literal character followed
# by plain text rather than an actual list item.
_UNICODE_BULLET_RE = re.compile(r"^([ \t]*)[•‣◦▪]\s*", re.MULTILINE)
# A "[TAG]" or "[Some Label]" at the very start of a line - the model's
# stand-in for emphasis when it doesn't use real Markdown **bold**.
_LEADING_BRACKET_TAG_RE = re.compile(r"^([ \t]*)\[([^\]\n]{1,60})\](?!\()\s?", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _ensure_paragraph_breaks(text: str) -> str:
    """CommonMark (what react-markdown renders) only starts a new paragraph
    on a *blank* line - a single newline is just whitespace, so two adjacent
    facts the model wrote on separate lines with a single break between them
    collapse into one run-together block of text once rendered. This was the
    actual cause of "the output is unreadable" even after banners/bullets/tags
    were cleaned up: the content was right, but every line the model intended
    as visually distinct was rendering as one dense paragraph. Inserts a
    blank line between every pair of adjacent non-blank lines so each becomes
    its own paragraph.

    Two carve-outs, both learned from a real broken render, not guessed in
    advance:
    - Markdown table rows (lines starting/ending with "|") must stay on
      consecutive lines with no blank line between them, or GFM parses them
      as disconnected fragments of literal pipe characters instead of a table.
    - Consecutive "- item"/"1. item" list lines must ALSO stay tight. A blank
      line between them makes remark-gfm render a "loose" list, where each
      item's text gets wrapped in a block-level <p> - and a block element
      inside <li> starts on its own line, pushing the bullet marker onto a
      line by itself above the (now visually orphaned) text. A normal "tight"
      list keeps the marker inline with its text, which is what every list
      here actually needs.
    """
    lines = text.split("\n")
    out: List[str] = []
    for i, line in enumerate(lines):
        out.append(line)
        if i == len(lines) - 1:
            continue
        next_line = lines[i + 1]
        if line.strip() == "" or next_line.strip() == "":
            continue
        if _TABLE_ROW_RE.match(line) and _TABLE_ROW_RE.match(next_line):
            continue
        if _LIST_ITEM_RE.match(line) and _LIST_ITEM_RE.match(next_line):
            continue
        out.append("")
    return "\n".join(out)


def _normalize_to_markdown(text: str) -> str:
    """Best-effort cleanup for the common "almost Markdown" patterns models
    fall back to despite prompts.py explicitly asking for real Markdown (see
    each agent's "FORMATTING RULE" instruction) - prompting alone measurably
    reduced but did not eliminate `[BRACKET] tags`, `• unicode bullets`, and
    `=== BANNER ===` lines in place of **bold**, "- " list items, and no
    redundant framing. Rather than keep iterating on instructions the model
    doesn't reliably follow, this makes the *rendered* result consistent
    regardless: banners are dropped, bullets become real Markdown list items,
    and a leading bracket tag becomes a bold label - so
    frontend/src/components/Markdown.tsx has something real to render either
    way. Applied to both the LLM-generated agent_log AND the deterministic
    fallback_msg text each node builds (see e.g. discovery_agent's
    fallback_msg), since the fallback strings use this same "[OK]"/"[ALERT]"
    convention - one pass covers both sources consistently."""
    text = _BANNER_LINE_RE.sub("", text)
    text = _UNICODE_BULLET_RE.sub(r"\1- ", text)
    text = _LEADING_BRACKET_TAG_RE.sub(lambda m: f"{m.group(1)}**{m.group(2)}** ", text)
    text = _ensure_paragraph_breaks(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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

    assessment_id = state.get("assessment_id", "")

    def _search_tool_executor(tool_name: str, tool_input: Dict[str, Any]) -> str:
        return agent_tools.search_schema_graph(
            query=tool_input.get("query", ""),
            services=services,
            dependencies=dependencies,
            assessment_id=assessment_id,
            node_type=tool_input.get("node_type"),
        )

    raw_output = invoke_agentic(
        sys_prompt, usr_prompt, agent_tools.SEARCH_SCHEMA_GRAPH_TOOL_SPEC, _search_tool_executor,
        "Discovery Agent", fallback_msg, assessment_id=assessment_id,
    )
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_discovery(narrative, orphans, shared_db_discoveries)

    logs.append({
        "agent": "Discovery Agent",
        "message": llm_output,
        "type": "discovery",
        "source": _log_source(raw_output, fallback_msg),
    })
    
    # Doesn't touch "iterations" - that field counts Planner<->Risk revision
    # rounds (incremented by planner_agent, checked by risk_agent), and
    # discovery_agent only ever runs once per pipeline execution (it's the
    # entry point, nothing loops back to it). It used to increment this here
    # too - a leftover from the since-removed self-retry loop - which made
    # risk_agent's iteration cap check fire one revision round earlier than
    # intended on every single run.
    return {"negotiation_logs": logs}


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
                "cycle_names": cycle_names,
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

    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Dependency Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_dependency(narrative, decoupling_strategies)

    logs.append({
        "agent": "Dependency Agent",
        "message": llm_output,
        "type": "dependency",
        "source": _log_source(raw_output, fallback_msg),
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

    # Read the structured objection list risk_agent actually computed (passed
    # via state, see AgentState.objections) rather than scanning
    # negotiation_logs for a literal "[OBJECTION]" tag - that tag only ever
    # appears in risk_agent's own deterministic fallback text, so once a real
    # LLM call succeeded there (extracting its agent_log narrative instead),
    # this always came back empty and the revision branch below silently
    # never ran.
    objections = state.get("objections", [])

    monolith_moved = False
    adjustments: List[str] = []
    if objections and iterations < constants.PLANNER_MAX_ITERATIONS:
        monolith_in_wave_1 = any(node == "monolith" for node in waves[0])
        if monolith_in_wave_1 and len(waves) > 1:
            new_w1 = [n for n in waves[0] if n != "monolith"]
            new_w2 = list(waves[1])
            if "monolith" not in new_w2:
                new_w2.append("monolith")
            waves = [new_w1, new_w2] + waves[2:]
            monolith_moved = True

        fallback_msg = f"Planner Agent (Revision Iteration #{iterations}):\n"
        fallback_msg += "- [ADJUSTMENT] Restructuring migration waves based on Risk Agent feedback:\n"
        if monolith_moved:
            adjustments.append("Moved 'Legacy Core Monolith' from Wave 1 to Wave 2 to allow database and authentication dependencies to migrate first.")
            fallback_msg += "  - Moved 'Legacy Core Monolith' from Wave 1 to Wave 2 to allow database and authentication dependencies to migrate first.\n"
        for obj in objections:
            adjustments.append(f"Addressed objection: {obj}")
            fallback_msg += f"  - Addressing objection: {obj}\n"
        fallback_msg += "- [OK] Proposed adjusted waves to Risk Agent."
    else:
        fallback_msg = "Planner Agent Initialization:\n"
        fallback_msg += "- [PROPOSAL] Generated base migration sequencing using topological layout:\n"
        for i, wave in enumerate(waves):
            wave_names = [next(s["name"] for s in services if s["id"] == cid) for cid in wave]
            fallback_msg += f"  - Wave {i+1}: {', '.join(wave_names)}\n"
        fallback_msg += "- [OK] Submitted wave proposal to Risk Agent for validation."

    id_to_name = {s["id"]: s["name"] for s in services}
    waves_named = [[id_to_name.get(cid, cid) for cid in wave] for wave in waves]

    sys_prompt = prompts.PLANNER_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.PLANNER_AGENT_USER_PROMPT.format(
        services_json=json.dumps([{"id": s["id"], "name": s["name"]} for s in services]),
        dependencies_json=json.dumps(dependencies),
        objections_json=json.dumps(objections),
        iteration=iterations
    )

    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Planner Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_planner(narrative, waves_named, adjustments)

    logs.append({
        "agent": "Planner Agent",
        "message": llm_output,
        "type": "planner",
        "source": _log_source(raw_output, fallback_msg),
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

    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Risk Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    name_by_id = {s["id"]: s["name"] for s in services}
    llm_output = response_formatter.format_risk(narrative, risk_assessment, name_by_id, objections)

    logs.append({
        "agent": "Risk Agent",
        "message": llm_output,
        "type": "risk",
        "source": _log_source(raw_output, fallback_msg),
    })

    return {
        "risk_assessment": risk_assessment,
        "negotiation_logs": logs,
        "satisfied": satisfied,
        "objections": objections,
    }


# --- Master Orchestrator: additional agent nodes (full 12-agent pipeline) ---

def digital_twin_agent(state: AgentState) -> Dict[str, Any]:
    """
    Builds the Enterprise Digital Twin: React Flow node/edge shapes plus a Neo4j
    entity summary, from the services/dependencies already in state.
    """
    logs = list(state.get("negotiation_logs", []))
    services = state["services"]
    dependencies = state["dependencies"]

    react_flow_nodes = [
        {
            "id": s["id"],
            "data": {
                "label": s["name"],
                "type": s.get("type", "Microservice"),
                "business_value": s.get("business_value", "Medium"),
            },
            "type": "default",
        }
        for s in services
    ]
    react_flow_edges = [
        {
            "id": f"{e['source']}-{e['target']}",
            "source": e["source"],
            "target": e["target"],
            "label": e.get("type", "Sync"),
        }
        for e in dependencies
    ]

    node_type_breakdown: Dict[str, int] = {}
    for s in services:
        t = s.get("type", "Microservice")
        node_type_breakdown[t] = node_type_breakdown.get(t, 0) + 1

    digital_twin = {
        "nodes": react_flow_nodes,
        "edges": react_flow_edges,
        "node_type_breakdown": node_type_breakdown,
        "neo4j_entity_count": len(services) + len(dependencies),
    }

    fallback_msg = "Digital Twin Agent Report:\n"
    fallback_msg += f"- [OK] Rendered {len(react_flow_nodes)} nodes and {len(react_flow_edges)} edges as the live Enterprise Digital Twin.\n"
    fallback_msg += f"- [INFO] Node type breakdown: {node_type_breakdown}."

    sys_prompt = prompts.DIGITAL_TWIN_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.DIGITAL_TWIN_AGENT_USER_PROMPT.format(
        node_count=len(react_flow_nodes),
        nodes_json=json.dumps(react_flow_nodes),
        edge_count=len(react_flow_edges),
        edges_json=json.dumps(react_flow_edges),
    )
    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Enterprise Digital Twin Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_digital_twin(narrative, node_type_breakdown)
    logs.append({"agent": "Enterprise Digital Twin Agent", "message": llm_output, "type": "digital_twin", "source": _log_source(raw_output, fallback_msg)})

    return {"digital_twin": digital_twin, "negotiation_logs": logs}


def migration_graph_agent(state: AgentState) -> Dict[str, Any]:
    """
    Connects applications, databases, queues/ETL edges, and discovered external
    systems (plus already-computed decoupling strategies) into one knowledge graph.
    """
    logs = list(state.get("negotiation_logs", []))
    services = state["services"]
    dependencies = state["dependencies"]
    decoupling_strategies = state.get("decoupling_strategies", [])

    applications = [s for s in services if s.get("type") not in ("Database", "Queue")]
    databases = [s for s in services if s.get("type") == "Database"]
    queues_or_etl = [e for e in dependencies if e.get("type") in ("MQ", "Async")]
    external_systems = [s for s in services if s.get("status") == "Discovered"]

    migration_graph = {
        "entities": {
            "applications": [a["id"] for a in applications],
            "databases": [d["id"] for d in databases],
            "queues_or_etl": [f"{q['source']}->{q['target']}" for q in queues_or_etl],
            "external_systems": [ext["id"] for ext in external_systems],
        },
        "decoupling_strategies": decoupling_strategies,
    }

    fallback_msg = "Migration Intelligence Graph Agent Report:\n"
    fallback_msg += (
        f"- [OK] Connected {len(applications)} applications, {len(databases)} databases, "
        f"{len(queues_or_etl)} queue/ETL edges, {len(external_systems)} externally-discovered "
        f"systems into one knowledge graph.\n"
    )
    if decoupling_strategies:
        fallback_msg += f"- [INFO] {len(decoupling_strategies)} decoupling strategy(ies) folded into graph relationships."

    sys_prompt = prompts.MIGRATION_GRAPH_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.MIGRATION_GRAPH_AGENT_USER_PROMPT.format(
        services_json=json.dumps([{"id": s["id"], "name": s["name"], "type": s.get("type")} for s in services]),
        dependencies_json=json.dumps(dependencies),
        decoupling_json=json.dumps(decoupling_strategies),
    )
    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Migration Intelligence Graph Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_migration_graph(narrative, migration_graph["entities"], len(decoupling_strategies))
    logs.append({"agent": "Migration Intelligence Graph Agent", "message": llm_output, "type": "migration_graph", "source": _log_source(raw_output, fallback_msg)})

    return {"migration_graph": migration_graph, "negotiation_logs": logs}


def complexity_agent(state: AgentState) -> Dict[str, Any]:
    """
    Estimates Architecture/Business/Technology/Integration/Migration complexity from
    real topology attributes, and derives engineering effort, timeline, and team size.
    """
    logs = list(state.get("negotiation_logs", []))
    services = state["services"]
    dependencies = state["dependencies"]
    cycle_count = len(state.get("decoupling_strategies", []))

    num_services = max(len(services), 1)
    avg_fan_out = len(dependencies) / num_services
    architecture_score = min(1.0, (avg_fan_out / 3.0) + (cycle_count * 0.1))

    high_value_count = sum(1 for s in services if s.get("business_value") == "High")
    business_score = min(1.0, high_value_count / num_services)

    distinct_runtimes = {s.get("runtime", "Unknown") for s in services}
    technology_score = min(1.0, len(distinct_runtimes) / num_services)

    high_crit_edges = sum(1 for e in dependencies if e.get("criticality") == "High" or e.get("type") == "Sync")
    integration_score = min(1.0, high_crit_edges / max(len(dependencies), 1))

    complexity_weight_map = {"High": 1.0, "Medium": 0.5, "Low": 0.2}
    migration_score = sum(
        complexity_weight_map.get(s.get("migration_complexity", "Medium"), 0.5) for s in services
    ) / num_services

    complexity_score = round(
        architecture_score * constants.COMPLEXITY_WEIGHT_ARCHITECTURE
        + business_score * constants.COMPLEXITY_WEIGHT_BUSINESS
        + technology_score * constants.COMPLEXITY_WEIGHT_TECHNOLOGY
        + integration_score * constants.COMPLEXITY_WEIGHT_INTEGRATION
        + migration_score * constants.COMPLEXITY_WEIGHT_MIGRATION,
        2,
    )

    total_base_duration = sum(s.get("base_duration", 14) for s in services)
    engineering_effort_days = round(total_base_duration * (0.5 + complexity_score))
    team_size = max(
        constants.COMPLEXITY_TEAM_SIZE_MIN,
        round(engineering_effort_days / constants.COMPLEXITY_TEAM_SIZE_DIVISOR),
    )
    estimated_timeline_weeks = max(1, round(engineering_effort_days / max(team_size, 1) / 5))

    complexity = {
        "complexity_score": complexity_score,
        "dimension_scores": {
            "architecture": round(architecture_score, 2),
            "business": round(business_score, 2),
            "technology": round(technology_score, 2),
            "integration": round(integration_score, 2),
            "migration": round(migration_score, 2),
        },
        "engineering_effort_days": engineering_effort_days,
        "estimated_timeline_weeks": estimated_timeline_weeks,
        "team_size": team_size,
    }

    fallback_msg = "Complexity Assessment Agent Report:\n"
    fallback_msg += (
        f"- [OK] Overall complexity score: {complexity_score} (architecture={architecture_score:.2f}, "
        f"business={business_score:.2f}, technology={technology_score:.2f}, "
        f"integration={integration_score:.2f}, migration={migration_score:.2f}).\n"
    )
    fallback_msg += (
        f"- [ESTIMATE] Engineering effort: {engineering_effort_days} person-days, "
        f"~{estimated_timeline_weeks} weeks with a team of {team_size}."
    )

    sys_prompt = prompts.COMPLEXITY_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.COMPLEXITY_AGENT_USER_PROMPT.format(
        service_count=len(services),
        services_json=json.dumps([{"id": s["id"], "migration_complexity": s.get("migration_complexity")} for s in services]),
        dependency_count=len(dependencies),
        dependencies_json=json.dumps(dependencies),
        cycle_count=cycle_count,
    )
    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Complexity Assessment Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_complexity(narrative, complexity["dimension_scores"], engineering_effort_days, estimated_timeline_weeks, team_size)
    logs.append({"agent": "Complexity Assessment Agent", "message": llm_output, "type": "complexity", "source": _log_source(raw_output, fallback_msg)})

    return {"complexity": complexity, "negotiation_logs": logs}


def enterprise_risk_agent(state: AgentState) -> Dict[str, Any]:
    """
    Portfolio-level Risk Assessment Agent: scores 8 risk categories from real topology
    data. Distinct from the wave-sequencing `risk_agent` used by run_agent_negotiation -
    this one runs before planning, matching the master pipeline's stated order.
    """
    logs = list(state.get("negotiation_logs", []))
    services = state["services"]
    dependencies = state["dependencies"]
    cycle_count = len(state.get("decoupling_strategies", []))

    nodes_with_edges = set()
    for e in dependencies:
        nodes_with_edges.add(e["source"])
        nodes_with_edges.add(e["target"])
    orphans = [s["id"] for s in services if s["id"] not in nodes_with_edges]

    num_services = max(len(services), 1)
    complexity_weight_map = {"High": 1.0, "Medium": 0.5, "Low": 0.2}

    technical_score = sum(
        complexity_weight_map.get(s.get("migration_complexity", "Medium"), 0.5) for s in services
    ) / num_services
    business_score = sum(1 for s in services if s.get("business_value") == "High") / num_services
    compliance_score = min(1.0, sum(1 for s in services if s.get("type") == "Database") / num_services)
    security_score = min(1.0, len(orphans) / num_services)
    operational_score = min(1.0, cycle_count * 0.2)
    high_crit_sync = sum(1 for e in dependencies if e.get("type") == "Sync" and e.get("criticality") == "High")
    performance_score = min(1.0, high_crit_sync / max(len(dependencies), 1))
    legacy_score = sum(1 for s in services if s.get("status") == "Legacy") / num_services
    data_migration_score = min(1.0, sum(1 for e in dependencies if e.get("type") == "DB") / max(len(dependencies), 1))

    category_scores = {
        "technical": round(technical_score, 2),
        "business": round(business_score, 2),
        "compliance": round(compliance_score, 2),
        "security": round(security_score, 2),
        "operational": round(operational_score, 2),
        "performance": round(performance_score, 2),
        "legacy": round(legacy_score, 2),
        "data_migration": round(data_migration_score, 2),
    }
    risk_score = round(sum(category_scores.values()) / len(category_scores), 2)

    top_risks = []
    if orphans:
        top_risks.append(f"Orphaned/disconnected services with no declared dependencies: {', '.join(orphans)}")
    if cycle_count:
        top_risks.append(f"{cycle_count} circular dependency cycle(s) increase operational rollback risk during migration")
    if high_crit_sync:
        top_risks.append(f"{high_crit_sync} high-criticality synchronous dependency edge(s) increase performance risk")
    if legacy_score > 0.5:
        top_risks.append(f"{int(legacy_score * 100)}% of services remain on legacy status")

    mitigation_strategies = []
    if orphans:
        mitigation_strategies.append("Audit orphaned services before migration to confirm they are truly decommissionable.")
    if cycle_count:
        mitigation_strategies.append("Apply the decoupling strategies already proposed by the Dependency Analysis Agent before sequencing waves.")
    if high_crit_sync:
        mitigation_strategies.append("Introduce async messaging or caching for high-criticality synchronous calls prior to migration.")

    enterprise_risk = {
        "risk_score": risk_score,
        "category_scores": category_scores,
        "top_risks": top_risks,
        "mitigation_strategies": mitigation_strategies,
    }

    fallback_msg = "Risk Assessment Agent Report:\n"
    fallback_msg += f"- [OK] Overall enterprise risk score: {int(risk_score * 100)}%.\n"
    for r in top_risks:
        fallback_msg += f"  - [RISK] {r}\n"
    for m in mitigation_strategies:
        fallback_msg += f"  - [MITIGATION] {m}\n"
    if risk_score > constants.SIMULATION_RISK_FORCE_ALL_THRESHOLD:
        fallback_msg += (
            f"- [ALERT] Risk score exceeds {int(constants.SIMULATION_RISK_FORCE_ALL_THRESHOLD * 100)}% "
            f"threshold - Simulation Agent will evaluate all migration strategies."
        )

    sys_prompt = prompts.ENTERPRISE_RISK_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.ENTERPRISE_RISK_AGENT_USER_PROMPT.format(
        service_count=len(services),
        services_json=json.dumps([{"id": s["id"], "name": s["name"]} for s in services]),
        dependency_count=len(dependencies),
        dependencies_json=json.dumps(dependencies),
        cycle_count=cycle_count,
        orphans_json=json.dumps(orphans),
    )
    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Risk Assessment Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_enterprise_risk(narrative, category_scores, top_risks, mitigation_strategies)
    logs.append({"agent": "Risk Assessment Agent", "message": llm_output, "type": "enterprise_risk", "source": _log_source(raw_output, fallback_msg)})

    return {"enterprise_risk": enterprise_risk, "negotiation_logs": logs}


def cloud_readiness_agent(state: AgentState) -> Dict[str, Any]:
    """
    Scores Azure/AWS/Google Cloud readiness from complexity, enterprise risk, and
    detected runtimes; recommends the best-fit platform.
    """
    logs = list(state.get("negotiation_logs", []))
    services = state["services"]
    complexity = state.get("complexity", {})
    enterprise_risk = state.get("enterprise_risk", {})

    complexity_score = complexity.get("complexity_score", 0.5)
    risk_score = enterprise_risk.get("risk_score", 0.5)

    high_value_count = sum(1 for s in services if s.get("business_value") == "High")
    business_value_score = high_value_count / max(len(services), 1)

    readiness_score = round(
        max(
            0.0,
            min(
                1.0,
                1.0
                - complexity_score * constants.CLOUD_READINESS_WEIGHT_COMPLEXITY
                - risk_score * constants.CLOUD_READINESS_WEIGHT_RISK
                + business_value_score * constants.CLOUD_READINESS_WEIGHT_BUSINESS_VALUE,
            ),
        ),
        2,
    )

    platform_keywords = {
        "Azure": ["dotnet", ".net", "c#", "windows", "sql server", "mssql", "azure"],
        "AWS": ["java", "node", "javascript", "postgresql", "mysql", "dynamodb", "aws"],
        "GoogleCloud": ["python", "kubernetes", "bigquery", "tensorflow", "gcp"],
    }
    platform_counts = {p: 0 for p in platform_keywords}
    for s in services:
        runtime = str(s.get("runtime", "")).lower()
        for platform, keywords in platform_keywords.items():
            if any(k in runtime for k in keywords):
                platform_counts[platform] += 1

    max_count = max(platform_counts.values()) or 1
    platform_scores = {
        p: round((0.5 * readiness_score) + (0.5 * (count / max_count)), 2)
        for p, count in platform_counts.items()
    }
    recommended_platform = max(platform_scores, key=platform_scores.get)

    cloud_readiness = {
        "readiness_score": readiness_score,
        "platform_scores": platform_scores,
        "recommended_platform": recommended_platform,
    }

    fallback_msg = "Cloud Readiness Agent Report:\n"
    fallback_msg += f"- [OK] Overall migration readiness score: {int(readiness_score * 100)}%.\n"
    fallback_msg += f"- [SCORES] {platform_scores}\n"
    fallback_msg += f"- [RECOMMENDATION] {recommended_platform} is the best-fit target platform based on detected runtimes.\n"
    if readiness_score < constants.MODERNIZATION_READINESS_THRESHOLD:
        fallback_msg += (
            f"- [FLAG] Readiness below {int(constants.MODERNIZATION_READINESS_THRESHOLD * 100)}% threshold - "
            f"modernization before migration is recommended."
        )

    sys_prompt = prompts.CLOUD_READINESS_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.CLOUD_READINESS_AGENT_USER_PROMPT.format(
        services_json=json.dumps([{"id": s["id"], "runtime": s.get("runtime")} for s in services]),
        complexity_json=json.dumps(complexity),
        risk_json=json.dumps(enterprise_risk),
    )
    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Cloud Readiness Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_cloud_readiness(narrative, platform_scores, recommended_platform)
    logs.append({"agent": "Cloud Readiness Agent", "message": llm_output, "type": "cloud_readiness", "source": _log_source(raw_output, fallback_msg)})

    return {"cloud_readiness": cloud_readiness, "negotiation_logs": logs}


def simulation_agent(state: AgentState) -> Dict[str, Any]:
    """
    Runs 3 what-if scenarios (Lift & Shift / Replatform / Refactor) by scaling real
    node cost/duration/risk through the existing Monte Carlo engine per strategy.
    """
    logs = list(state.get("negotiation_logs", []))
    services = state["services"]
    enterprise_risk = state.get("enterprise_risk", {})
    complexity = state.get("complexity", {})
    cloud_readiness = state.get("cloud_readiness", {})

    overall_risk = enterprise_risk.get("risk_score", 0.0)
    readiness_score = cloud_readiness.get("readiness_score", 0.0)
    base_effort_days = complexity.get("engineering_effort_days", 0)
    force_all = overall_risk > constants.SIMULATION_RISK_FORCE_ALL_THRESHOLD

    total_revenue_impact = sum(s.get("revenue_impact", 0.0) for s in services)

    scenarios: Dict[str, Any] = {}
    for strategy, multipliers in constants.SIMULATION_STRATEGY_MULTIPLIERS.items():
        scaled_nodes = [
            ServiceNode(
                **{
                    **s,
                    "base_cost": s.get("base_cost", 10000.0) * multipliers["cost_factor"],
                    "base_duration": round(s.get("base_duration", 14) * multipliers["duration_factor"]),
                }
            )
            for s in services
        ]
        scenario_risk = round(min(1.0, overall_risk * multipliers["risk_factor"]), 2)
        risk_scaled_nodes = [n.model_copy(update={"failure_probability": scenario_risk}) for n in scaled_nodes]

        monte_carlo = run_monte_carlo(
            nodes=scaled_nodes,
            impacted_nodes=risk_scaled_nodes,
            num_simulations=settings.MAX_SIMULATION_RUNS,
        )

        scenarios[strategy] = {
            "risk": scenario_risk,
            "duration_days": monte_carlo.expected_duration,
            "cost_usd": monte_carlo.expected_cost,
            "engineering_effort_days": round(base_effort_days * multipliers["duration_factor"]),
            "business_impact_usd": round(total_revenue_impact * scenario_risk, 2),
            "cloud_readiness": readiness_score,
            "confidence": round(max(0.0, 1.0 - scenario_risk), 2),
        }

    simulation_results = {
        "scenarios": scenarios,
        "force_all_strategies": force_all,
    }

    fallback_msg = "Simulation Agent Report:\n"
    for strategy, res in scenarios.items():
        fallback_msg += (
            f"- [{strategy}] risk={int(res['risk'] * 100)}%, duration={res['duration_days']}d, "
            f"cost=${res['cost_usd']:,.0f}, confidence={int(res['confidence'] * 100)}%\n"
        )
    if force_all:
        fallback_msg += (
            f"- [ALERT] Enterprise risk {int(overall_risk * 100)}% exceeded the "
            f"{int(constants.SIMULATION_RISK_FORCE_ALL_THRESHOLD * 100)}% threshold - all migration "
            f"strategies were evaluated."
        )

    sys_prompt = prompts.SIMULATION_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.SIMULATION_AGENT_USER_PROMPT.format(
        scenarios_json=json.dumps(scenarios),
        risk_score=overall_risk,
        force_all=force_all,
    )
    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Simulation Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_simulation(narrative, scenarios)
    logs.append({"agent": "Simulation Agent", "message": llm_output, "type": "simulation", "source": _log_source(raw_output, fallback_msg)})

    return {"simulation_results": simulation_results, "negotiation_logs": logs}


def recommendation_agent(state: AgentState) -> Dict[str, Any]:
    """
    Synthesizes a recommended migration strategy and stakeholder-specific
    recommendations from the simulation comparison, complexity, and cloud readiness.

    Runs exactly once per pipeline execution. This used to loop back on itself
    (via `_route_after_recommendation`, now removed) whenever confidence_score
    came out under RECOMMENDATION_CONFIDENCE_THRESHOLD (85%) - but the "retry"
    did no additional analysis, just added a flat +0.05 to whatever confidence
    the composite formula below already produced, and that formula (average of
    the simulation's scenario confidence and cloud readiness score) routinely
    lands well under 85% on realistic inputs - so the loop fired on nearly
    every run, silently doubling this stage's LLM latency for a result a flat
    nudge could've produced without a second round trip. Removed rather than
    kept-but-fixed since the "rerun with historical context" it advertised
    never actually incorporated any context - the single deterministic pass
    below is exactly as informed as either of the two calls it replaces.
    """
    logs = list(state.get("negotiation_logs", []))
    simulation_results = state.get("simulation_results", {})
    complexity = state.get("complexity", {})
    cloud_readiness = state.get("cloud_readiness", {})
    scenarios = simulation_results.get("scenarios", {})
    readiness_score = cloud_readiness.get("readiness_score", 0.0)

    if scenarios:
        max_duration = max(r["duration_days"] for r in scenarios.values()) or 1
        max_cost = max(r["cost_usd"] for r in scenarios.values()) or 1

        def _composite(r: Dict[str, Any]) -> float:
            return r["risk"] * 0.5 + (r["duration_days"] / max_duration) * 0.25 + (r["cost_usd"] / max_cost) * 0.25

        recommended_strategy = min(scenarios, key=lambda k: _composite(scenarios[k]))
        chosen = scenarios[recommended_strategy]
        confidence_score = round((chosen["confidence"] + readiness_score) / 2, 2)
    else:
        recommended_strategy = "Replatform"
        confidence_score = 0.5

    if readiness_score < constants.MODERNIZATION_READINESS_THRESHOLD:
        modernization_recommendation = (
            f"Migration readiness ({int(readiness_score * 100)}%) is below the "
            f"{int(constants.MODERNIZATION_READINESS_THRESHOLD * 100)}% threshold - modernize core legacy "
            f"components before attempting migration."
        )
    else:
        modernization_recommendation = "No pre-migration modernization required; readiness is above threshold."

    recommendation = {
        "recommended_strategy": recommended_strategy,
        "engineering_recommendation": (
            f"Adopt {recommended_strategy} for the sequenced migration waves; engineering effort is "
            f"estimated at {complexity.get('engineering_effort_days', 'N/A')} person-days."
        ),
        "business_recommendation": (
            f"{recommended_strategy} balances risk and cost given the current portfolio; expected cost "
            f"${scenarios.get(recommended_strategy, {}).get('cost_usd', 0):,.0f}."
        ),
        "modernization_recommendation": modernization_recommendation,
        "customer_recommendation": (
            f"We recommend a {recommended_strategy} approach, with {int(confidence_score * 100)}% confidence "
            f"based on your current architecture, risk, and cloud readiness."
        ),
        "confidence_score": confidence_score,
    }

    fallback_msg = "Recommendation Agent Report:\n"
    fallback_msg += f"- [RECOMMENDED STRATEGY] {recommended_strategy} (confidence {int(confidence_score * 100)}%)\n"
    fallback_msg += f"- [MODERNIZATION] {modernization_recommendation}"

    sys_prompt = prompts.RECOMMENDATION_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.RECOMMENDATION_AGENT_USER_PROMPT.format(
        recommended_strategy=recommended_strategy,
        confidence_score=confidence_score,
        simulation_json=json.dumps(scenarios),
        complexity_json=json.dumps(complexity),
        cloud_readiness_json=json.dumps(cloud_readiness),
        readiness_score=readiness_score,
    )
    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Recommendation Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_recommendation(
        narrative,
        recommended_strategy,
        confidence_score,
        recommendation["engineering_recommendation"],
        recommendation["business_recommendation"],
        recommendation["modernization_recommendation"],
        recommendation["customer_recommendation"],
    )
    logs.append({"agent": "Recommendation Agent", "message": llm_output, "type": "recommendation", "source": _log_source(raw_output, fallback_msg)})

    return {
        "recommendation": recommendation,
        "negotiation_logs": logs,
        "confidence_score": confidence_score,
    }


def explainability_agent(state: AgentState) -> Dict[str, Any]:
    """
    Explains the recommendation citing only evidence already produced by prior
    agents - no new computation, purely traceability over existing state.
    """
    logs = list(state.get("negotiation_logs", []))
    recommendation = state.get("recommendation", {})
    decoupling_strategies = state.get("decoupling_strategies", [])
    enterprise_risk = state.get("enterprise_risk", {})
    complexity = state.get("complexity", {})

    evidence = []
    dependencies_considered = []
    for strat in decoupling_strategies:
        dependencies_considered.append(" -> ".join(strat.get("cycle", [])))
        evidence.append(strat.get("description", ""))

    risks_considered = list(enterprise_risk.get("top_risks", []))

    confidence_explanation = (
        f"Confidence of {int(recommendation.get('confidence_score', 0.0) * 100)}% derives from an enterprise "
        f"risk score of {int(enterprise_risk.get('risk_score', 0.0) * 100)}% and an overall complexity score "
        f"of {complexity.get('complexity_score', 0.0)}."
    )

    explainability = {
        "evidence": evidence,
        "dependencies_considered": dependencies_considered,
        "risks_considered": risks_considered,
        "confidence_explanation": confidence_explanation,
    }

    fallback_msg = "Explainability Agent Report:\n"
    fallback_msg += (
        f"- [WHY] Recommended strategy '{recommendation.get('recommended_strategy', 'N/A')}' is explained by "
        f"{len(evidence)} dependency/decoupling factor(s) and {len(risks_considered)} risk factor(s).\n"
    )
    fallback_msg += f"- [CONFIDENCE] {confidence_explanation}"

    sys_prompt = prompts.EXPLAINABILITY_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.EXPLAINABILITY_AGENT_USER_PROMPT.format(
        recommendation_json=json.dumps(recommendation),
        decoupling_json=json.dumps(decoupling_strategies),
        risk_json=json.dumps(enterprise_risk),
        complexity_json=json.dumps(complexity),
    )
    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Explainability Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_explainability(narrative, evidence, risks_considered, confidence_explanation)
    logs.append({"agent": "Explainability Agent", "message": llm_output, "type": "explainability", "source": _log_source(raw_output, fallback_msg)})

    return {"explainability": explainability, "negotiation_logs": logs}


def report_agent(state: AgentState) -> Dict[str, Any]:
    """
    Assembles the final executive report from every prior agent's output. PDF/DOCX
    generation is not implemented (no rendering library in requirements.txt) - only
    the JSON export is real; other formats are marked accordingly.
    """
    logs = list(state.get("negotiation_logs", []))
    services = state["services"]
    dependencies = state["dependencies"]

    assessment_summary = {
        "total_services": len(services),
        "total_dependencies": len(dependencies),
        "waves": state.get("proposed_waves", []),
    }

    fallback_msg = "Report Generation Agent Report:\n"
    fallback_msg += (
        f"- [SUMMARY] {len(services)} services, {len(dependencies)} dependencies assessed across "
        f"{len(state.get('proposed_waves', []))} migration wave(s). Recommended strategy: "
        f"{state.get('recommendation', {}).get('recommended_strategy', 'N/A')} "
        f"(confidence {int(state.get('confidence_score', 0.0) * 100)}%).\n"
    )
    fallback_msg += "- [OK] Executive report assembled. JSON export available; PDF/DOCX export not yet implemented."

    sys_prompt = prompts.REPORT_AGENT_SYSTEM_PROMPT
    usr_prompt = prompts.REPORT_AGENT_USER_PROMPT.format(
        assessment_summary_json=json.dumps(
            {
                "assessment_summary": assessment_summary,
                "complexity": state.get("complexity", {}),
                "risk": state.get("enterprise_risk", {}),
                "cloud_readiness": state.get("cloud_readiness", {}),
                "simulation_results": state.get("simulation_results", {}),
                "recommendation": state.get("recommendation", {}),
            }
        )
    )
    raw_output = execute_llm_prompt(sys_prompt, usr_prompt, "Report Generation Agent", fallback_msg, assessment_id=state.get("assessment_id", ""))
    narrative = _narrative_from_llm_output(raw_output)
    llm_output = response_formatter.format_report(
        narrative,
        len(services),
        len(dependencies),
        len(state.get("proposed_waves", [])),
        state.get("recommendation", {}).get("recommended_strategy", "N/A"),
        state.get("confidence_score", 0.0),
    )
    logs.append({"agent": "Report Generation Agent", "message": llm_output, "type": "report", "source": _log_source(raw_output, fallback_msg)})

    report = {
        "executive_summary": llm_output,
        "assessment_summary": assessment_summary,
        "download_formats": {
            "json": {"status": "available"},
            "pdf": {"status": "not_implemented"},
            "docx": {"status": "not_implemented"},
        },
    }

    return {"report": report, "negotiation_logs": logs}


# --- LangGraph Orchestrator & Copilot Chat ---

def run_agent_negotiation(
    services: List[Dict[str, Any]],
    dependencies: List[Dict[str, Any]],
    assessment_id: str = "",
) -> Dict[str, Any]:
    """
    Executes the multi-agent LangGraph coordination state machine with mandatory LLM tracing.
    `assessment_id` is optional - when set (see app/services_v1/agent_run_service.py),
    the Discovery step retrieves relevant context from that assessment's uploaded
    documents via RAG; the legacy global-graph /api/plan caller omits it.
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
        "assessment_id": assessment_id,
        "proposed_waves": [],
        "negotiation_logs": [],
        "risk_assessment": {},
        "decoupling_strategies": [],
        "iterations": 0,
        "satisfied": False,
        "objections": [],
        "objections": [],
    }

    final_output = app.invoke(initial_state)
    return final_output


def run_agent_negotiation_stream(
    services: List[Dict[str, Any]],
    dependencies: List[Dict[str, Any]],
    assessment_id: str = "",
):
    """Generator twin of run_agent_negotiation(): yields one negotiation-log
    entry (`{"agent", "message", "type"}`) as soon as each stage completes,
    then a final `{"type": "complete", "waves", "decoupling_strategies",
    "risk_assessment"}` event once the negotiation settles - lets a caller
    (see app/services_v1/agent_run_service.py's streaming endpoint) surface
    each agent's reasoning live instead of waiting for the whole (possibly
    multi-iteration) negotiation to finish. Builds the identical graph
    run_agent_negotiation() does; only the invocation differs
    (`.stream(..., stream_mode="values")`, which yields the full accumulated
    state after every node, instead of `.invoke()`)."""
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
        "assessment_id": assessment_id,
        "proposed_waves": [],
        "negotiation_logs": [],
        "risk_assessment": {},
        "decoupling_strategies": [],
        "iterations": 0,
        "satisfied": False,
        "objections": [],
    }

    seen_log_count = 0
    final_state: Dict[str, Any] = initial_state
    for state in app.stream(initial_state, stream_mode="values"):
        final_state = state
        logs = state.get("negotiation_logs", [])
        for entry in logs[seen_log_count:]:
            yield entry
        seen_log_count = len(logs)

    yield {
        "type": "complete",
        "waves": final_state.get("proposed_waves", []),
        "decoupling_strategies": final_state.get("decoupling_strategies", []),
        "risk_assessment": final_state.get("risk_assessment", {}),
    }


# --- Master Orchestrator: full 12-agent pipeline plumbing ---

_PIPELINE_NEXT_AGENT = {
    "Initialize State": "Discovery Agent",
    "Discovery Agent": "Dependency Analysis Agent",
    "Dependency Analysis Agent": "Enterprise Digital Twin Agent",
    "Enterprise Digital Twin Agent": "Migration Intelligence Graph Agent",
    "Migration Intelligence Graph Agent": "Complexity Assessment Agent",
    "Complexity Assessment Agent": "Risk Assessment Agent",
    "Risk Assessment Agent": "Cloud Readiness Agent",
    "Cloud Readiness Agent": "Migration Planner Agent",
    "Migration Planner Agent": "Simulation Agent",
    "Simulation Agent": "Recommendation Agent",
    "Recommendation Agent": "Explainability Agent",
    "Explainability Agent": "Report Generation Agent",
    "Report Generation Agent": "END",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wrap_node(fn, name: str):
    """
    Wraps an agent node with execution-history logging and the spec's "any agent
    fails twice -> HUMAN_REVIEW_REQUIRED" rule. Retries the SAME inputs up to
    `AGENT_MAX_RETRIES` extra times on exception before giving up.
    """

    def _node(state: AgentState) -> Dict[str, Any]:
        history = list(state.get("execution_history", []))
        last_error: Optional[Exception] = None

        for attempt in range(1, constants.AGENT_MAX_RETRIES + 2):
            try:
                result = fn(state)
                status = "COMPLETED" if attempt == 1 else "COMPLETED_ON_RETRY"
                history.append({"agent": name, "status": status, "attempt": attempt, "timestamp": _now_iso()})
                result["execution_history"] = history
                result["current_agent"] = name
                result["next_agent"] = _PIPELINE_NEXT_AGENT.get(name, "")
                return result
            except Exception as ex:
                last_error = ex
                history.append({"agent": name, "status": "FAILED", "attempt": attempt, "error": str(ex), "timestamp": _now_iso()})
                logger.warning(f"Agent '{name}' raised on attempt {attempt}: {ex}")

        retry_counts = dict(state.get("retry_counts", {}))
        retry_counts[name] = retry_counts.get(name, 0) + (constants.AGENT_MAX_RETRIES + 1)
        return {
            "execution_history": history,
            "retry_counts": retry_counts,
            "current_agent": name,
            "next_agent": "HUMAN_REVIEW_REQUIRED",
            "workflow_status": "HUMAN_REVIEW_REQUIRED",
            "status_reason": f"Agent '{name}' failed {constants.AGENT_MAX_RETRIES + 1} times: {last_error}",
        }

    return _node


def initialize_state_node(state: AgentState) -> Dict[str, Any]:
    """
    Entry-point node: seeds the full AssessmentState default fields. Leaves the
    caller-provided `services`/`dependencies` untouched (not part of this return dict).
    """
    return {
        "proposed_waves": [],
        "negotiation_logs": [],
        "risk_assessment": {},
        "decoupling_strategies": [],
        "iterations": 0,
        "satisfied": False,
        "objections": [],
        "digital_twin": {},
        "migration_graph": {},
        "complexity": {},
        "enterprise_risk": {},
        "cloud_readiness": {},
        "simulation_results": {},
        "recommendation": {},
        "explainability": {},
        "report": {},
        "confidence_score": 0.0,
        "retry_counts": {},
        "workflow_status": "RUNNING",
        "status_reason": "",
    }


def _make_linear_router(next_node: str):
    def _router(state: AgentState) -> str:
        if state.get("workflow_status") == "HUMAN_REVIEW_REQUIRED":
            return END
        return next_node

    return _router


def run_full_assessment(
    services: List[Dict[str, Any]],
    dependencies: List[Dict[str, Any]],
    assessment_id: str = "",
) -> Dict[str, Any]:
    """
    Executes the full Master Orchestrator pipeline:
    Initialize State -> Discovery -> Dependency -> Digital Twin -> Migration Graph ->
    Complexity -> Risk Assessment -> Cloud Readiness -> Migration Planner ->
    Simulation -> Recommendation -> Explainability -> Report.

    Risk Assessment used to conditionally branch into an early extra Simulation
    Agent pass when risk exceeded the force-all-strategies threshold, before
    routing into Cloud Readiness either way - removed 2026-07-31: that early
    pass ran before Cloud Readiness had computed anything, so its
    `cloud_readiness` figures were always the zero-value default, and its
    entire `simulation_results` output was then unconditionally overwritten by
    the later, unconditional post-Planner Simulation Agent pass anyway (same
    `simulation_agent` function, same state key). It cost a full Monte Carlo
    run plus a real LLM call, on every high-risk assessment, for output that
    was never read - the `force_all_strategies` flag it existed to compute is
    already correctly derived by the one remaining Simulation Agent pass
    regardless (it reads `enterprise_risk`, which by then is always populated).

    Kept separate from `run_agent_negotiation` (the existing 4-node negotiation loop),
    which stays untouched since `/api/plan` and its tests depend on its exact shape.
    """
    workflow = StateGraph(AgentState)

    # Node identifiers are suffixed with "_node" where they'd otherwise collide with an
    # AgentState field name of the same name - LangGraph forbids a node id that matches
    # one of the state's own channels (e.g. "complexity" the node vs "complexity" the key).
    workflow.add_node("initialize_state", _wrap_node(initialize_state_node, "Initialize State"))
    workflow.add_node("discovery", _wrap_node(discovery_agent, "Discovery Agent"))
    workflow.add_node("dependency", _wrap_node(dependency_agent, "Dependency Analysis Agent"))
    workflow.add_node("digital_twin_node", _wrap_node(digital_twin_agent, "Enterprise Digital Twin Agent"))
    workflow.add_node("migration_graph_node", _wrap_node(migration_graph_agent, "Migration Intelligence Graph Agent"))
    workflow.add_node("complexity_node", _wrap_node(complexity_agent, "Complexity Assessment Agent"))
    workflow.add_node("enterprise_risk_node", _wrap_node(enterprise_risk_agent, "Risk Assessment Agent"))
    workflow.add_node("cloud_readiness_node", _wrap_node(cloud_readiness_agent, "Cloud Readiness Agent"))
    workflow.add_node("planner", _wrap_node(planner_agent, "Migration Planner Agent"))
    workflow.add_node("simulation", _wrap_node(simulation_agent, "Simulation Agent"))
    workflow.add_node("recommendation_node", _wrap_node(recommendation_agent, "Recommendation Agent"))
    workflow.add_node("explainability_node", _wrap_node(explainability_agent, "Explainability Agent"))
    workflow.add_node("report_node", _wrap_node(report_agent, "Report Generation Agent"))

    workflow.set_entry_point("initialize_state")

    workflow.add_conditional_edges("initialize_state", _make_linear_router("discovery"))
    # Discovery/Dependency used to conditionally loop back on themselves once
    # if the spec's data-quality signal looked bad (no non-"Unknown" runtimes
    # detected / an empty dependency list) - removed for the same reason the
    # Recommendation Agent's confidence-retry loop above was removed: the
    # retry re-runs the exact same deterministic check against the exact same
    # unchanged `services`/`dependencies` input, so it can never actually
    # succeed where the first pass didn't. In practice, document-extracted
    # systems very often lack an explicit runtime/tech-stack mention, so this
    # unconditionally doubled Discovery Agent's (and sometimes Dependency
    # Agent's) LLM latency on every single run for zero benefit - not an
    # occasional edge case, but the common case.
    workflow.add_conditional_edges("discovery", _make_linear_router("dependency"))
    workflow.add_conditional_edges("dependency", _make_linear_router("digital_twin_node"))
    workflow.add_conditional_edges("digital_twin_node", _make_linear_router("migration_graph_node"))
    workflow.add_conditional_edges("migration_graph_node", _make_linear_router("complexity_node"))
    workflow.add_conditional_edges("complexity_node", _make_linear_router("enterprise_risk_node"))
    workflow.add_conditional_edges("enterprise_risk_node", _make_linear_router("cloud_readiness_node"))
    workflow.add_conditional_edges("cloud_readiness_node", _make_linear_router("planner"))
    workflow.add_conditional_edges("planner", _make_linear_router("simulation"))
    workflow.add_conditional_edges("simulation", _make_linear_router("recommendation_node"))
    workflow.add_conditional_edges("recommendation_node", _make_linear_router("explainability_node"))
    workflow.add_conditional_edges("explainability_node", _make_linear_router("report_node"))
    workflow.add_conditional_edges("report_node", lambda state: END)

    app = workflow.compile()

    initial_state: Dict[str, Any] = {
        "services": services,
        "dependencies": dependencies,
        "assessment_id": assessment_id,
        "proposed_waves": [],
        "negotiation_logs": [],
        "risk_assessment": {},
        "decoupling_strategies": [],
        "iterations": 0,
        "satisfied": False,
        "objections": [],
        "digital_twin": {},
        "migration_graph": {},
        "complexity": {},
        "enterprise_risk": {},
        "cloud_readiness": {},
        "simulation_results": {},
        "recommendation": {},
        "explainability": {},
        "report": {},
        "execution_history": [],
        "current_agent": "",
        "next_agent": "",
        "confidence_score": 0.0,
        "retry_counts": {},
        "workflow_status": "RUNNING",
        "status_reason": "",
    }

    final_state = app.invoke(initial_state)

    if final_state.get("workflow_status") != "HUMAN_REVIEW_REQUIRED":
        final_state["workflow_status"] = "COMPLETED"

    return final_state


def run_full_assessment_stream(
    services: List[Dict[str, Any]],
    dependencies: List[Dict[str, Any]],
    assessment_id: str = "",
):
    """Generator twin of run_full_assessment(): yields one negotiation-log
    entry as soon as each of the 12 pipeline agents completes, then a final
    "complete" event carrying every structured field the pipeline computed
    (waves/decoupling_strategies/risk_assessment plus complexity/
    enterprise_risk/cloud_readiness/simulation_results/recommendation/
    explainability/report/confidence_score/workflow_status) - same
    live-per-agent-progress contract as run_agent_negotiation_stream(),
    applied to the full Master Orchestrator pipeline instead of the smaller
    4-agent negotiation loop (see app/services_v1/agent_run_service.py's
    streaming endpoint, the only caller, which persists this whole event as
    AgentRun.final_result so app/services_v1/report_service.py can build a
    report straight from it without re-running anything). Builds the
    identical graph run_full_assessment() does; only the invocation differs
    (`.stream(..., stream_mode="values")` instead of `.invoke()`).

    Two behavioral differences from the 4-agent stream this replaced, worth
    knowing before relying on this: (1) there is no Planner<->Risk revision
    loop here - Migration Planner Agent runs exactly once, unconditionally;
    (2) this pipeline's risk step is Risk Assessment Agent (8-category
    enterprise risk scoring), not the 4-agent loop's Risk Agent (per-service
    risk/objections) - `risk_assessment` in the final "complete" event stays
    at its initial `{}` since nothing in this graph populates it (use
    `enterprise_risk` instead), and no negotiation-log entry will be named
    "Risk Agent" for a frontend that special-cases that exact name.
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("initialize_state", _wrap_node(initialize_state_node, "Initialize State"))
    workflow.add_node("discovery", _wrap_node(discovery_agent, "Discovery Agent"))
    workflow.add_node("dependency", _wrap_node(dependency_agent, "Dependency Analysis Agent"))
    workflow.add_node("digital_twin_node", _wrap_node(digital_twin_agent, "Enterprise Digital Twin Agent"))
    workflow.add_node("migration_graph_node", _wrap_node(migration_graph_agent, "Migration Intelligence Graph Agent"))
    workflow.add_node("complexity_node", _wrap_node(complexity_agent, "Complexity Assessment Agent"))
    workflow.add_node("enterprise_risk_node", _wrap_node(enterprise_risk_agent, "Risk Assessment Agent"))
    workflow.add_node("cloud_readiness_node", _wrap_node(cloud_readiness_agent, "Cloud Readiness Agent"))
    workflow.add_node("planner", _wrap_node(planner_agent, "Migration Planner Agent"))
    workflow.add_node("simulation", _wrap_node(simulation_agent, "Simulation Agent"))
    workflow.add_node("recommendation_node", _wrap_node(recommendation_agent, "Recommendation Agent"))
    workflow.add_node("explainability_node", _wrap_node(explainability_agent, "Explainability Agent"))
    workflow.add_node("report_node", _wrap_node(report_agent, "Report Generation Agent"))

    workflow.set_entry_point("initialize_state")

    workflow.add_conditional_edges("initialize_state", _make_linear_router("discovery"))
    # Discovery/Dependency used to conditionally loop back on themselves once
    # if the spec's data-quality signal looked bad (no non-"Unknown" runtimes
    # detected / an empty dependency list) - removed for the same reason the
    # Recommendation Agent's confidence-retry loop above was removed: the
    # retry re-runs the exact same deterministic check against the exact same
    # unchanged `services`/`dependencies` input, so it can never actually
    # succeed where the first pass didn't. In practice, document-extracted
    # systems very often lack an explicit runtime/tech-stack mention, so this
    # unconditionally doubled Discovery Agent's (and sometimes Dependency
    # Agent's) LLM latency on every single run for zero benefit - not an
    # occasional edge case, but the common case.
    workflow.add_conditional_edges("discovery", _make_linear_router("dependency"))
    workflow.add_conditional_edges("dependency", _make_linear_router("digital_twin_node"))
    workflow.add_conditional_edges("digital_twin_node", _make_linear_router("migration_graph_node"))
    workflow.add_conditional_edges("migration_graph_node", _make_linear_router("complexity_node"))
    workflow.add_conditional_edges("complexity_node", _make_linear_router("enterprise_risk_node"))
    # No longer branches into an early extra Simulation Agent pass when risk >
    # 80% - see run_full_assessment()'s docstring (identical pipeline, only
    # the invocation differs) for why that pass was pure waste.
    workflow.add_conditional_edges("enterprise_risk_node", _make_linear_router("cloud_readiness_node"))
    workflow.add_conditional_edges("cloud_readiness_node", _make_linear_router("planner"))
    workflow.add_conditional_edges("planner", _make_linear_router("simulation"))
    workflow.add_conditional_edges("simulation", _make_linear_router("recommendation_node"))
    workflow.add_conditional_edges("recommendation_node", _make_linear_router("explainability_node"))
    workflow.add_conditional_edges("explainability_node", _make_linear_router("report_node"))
    workflow.add_conditional_edges("report_node", lambda state: END)

    app = workflow.compile()

    initial_state: Dict[str, Any] = {
        "services": services,
        "dependencies": dependencies,
        "assessment_id": assessment_id,
        "proposed_waves": [],
        "negotiation_logs": [],
        "risk_assessment": {},
        "decoupling_strategies": [],
        "iterations": 0,
        "satisfied": False,
        "objections": [],
        "digital_twin": {},
        "migration_graph": {},
        "complexity": {},
        "enterprise_risk": {},
        "cloud_readiness": {},
        "simulation_results": {},
        "recommendation": {},
        "explainability": {},
        "report": {},
        "execution_history": [],
        "current_agent": "",
        "next_agent": "",
        "confidence_score": 0.0,
        "retry_counts": {},
        "workflow_status": "RUNNING",
        "status_reason": "",
    }

    seen_log_count = 0
    final_state: Dict[str, Any] = initial_state
    for state in app.stream(initial_state, stream_mode="values"):
        final_state = state
        logs = state.get("negotiation_logs", [])
        for entry in logs[seen_log_count:]:
            yield entry
        seen_log_count = len(logs)

    workflow_status = final_state.get("workflow_status", "RUNNING")
    if workflow_status != "HUMAN_REVIEW_REQUIRED":
        workflow_status = "COMPLETED"

    yield {
        "type": "complete",
        "waves": final_state.get("proposed_waves", []),
        "decoupling_strategies": final_state.get("decoupling_strategies", []),
        "risk_assessment": final_state.get("risk_assessment", {}),
        "complexity": final_state.get("complexity", {}),
        "enterprise_risk": final_state.get("enterprise_risk", {}),
        "cloud_readiness": final_state.get("cloud_readiness", {}),
        "simulation_results": final_state.get("simulation_results", {}),
        "recommendation": final_state.get("recommendation", {}),
        "explainability": final_state.get("explainability", {}),
        "report": final_state.get("report", {}),
        "confidence_score": final_state.get("confidence_score", 0.0),
        "workflow_status": workflow_status,
    }


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
