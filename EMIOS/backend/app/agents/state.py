from typing import TypedDict, List, Dict, Any

class AgentState(TypedDict):
    services: List[Dict[str, Any]]
    dependencies: List[Dict[str, Any]]
    proposed_waves: List[List[str]]
    negotiation_logs: List[Dict[str, Any]]
    risk_assessment: Dict[str, Any]
    decoupling_strategies: List[Dict[str, Any]]
    iterations: int
    satisfied: bool
