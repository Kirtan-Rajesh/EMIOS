from typing import TypedDict, List, Dict, Any

class AgentState(TypedDict):
    services: List[Dict[str, Any]]
    dependencies: List[Dict[str, Any]]
    # Optional - only set when a pipeline run is scoped to a persisted /api/v1
    # assessment (see app/services_v1/agent_run_service.py). When present,
    # discovery_agent uses it to pull relevant RAG context from that
    # assessment's uploaded documents (app/services/vector_search_service.py).
    # Absent/empty for the legacy global-graph /api/plan and /api/assess flows.
    assessment_id: str
    proposed_waves: List[List[str]]
    negotiation_logs: List[Dict[str, Any]]
    risk_assessment: Dict[str, Any]
    # Structured objection strings from the most recent risk_agent pass - what
    # planner_agent actually revises waves in response to. Passed as real
    # state (not re-derived by scanning negotiation_logs message text for a
    # literal "[OBJECTION]" tag), since that tag only ever appears in
    # risk_agent's deterministic fallback text - a real LLM's extracted
    # agent_log narrative has no reason to reproduce it verbatim, which
    # silently broke the whole revision loop once a real LLM was configured.
    objections: List[str]
    decoupling_strategies: List[Dict[str, Any]]
    iterations: int
    satisfied: bool

    # --- Full Master Orchestrator shared state (12-agent pipeline) ---
    digital_twin: Dict[str, Any]
    migration_graph: Dict[str, Any]
    complexity: Dict[str, Any]
    enterprise_risk: Dict[str, Any]
    cloud_readiness: Dict[str, Any]
    simulation_results: Dict[str, Any]
    recommendation: Dict[str, Any]
    explainability: Dict[str, Any]
    report: Dict[str, Any]
    execution_history: List[Dict[str, Any]]
    current_agent: str
    next_agent: str
    confidence_score: float
    retry_counts: Dict[str, int]
    workflow_status: str  # RUNNING, HUMAN_REVIEW_REQUIRED, COMPLETED
    status_reason: str
