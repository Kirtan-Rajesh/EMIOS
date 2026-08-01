from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class ServiceNode(BaseModel):
    id: str
    name: str
    type: str = "Microservice"  # Microservice, Monolith, Database, Queue
    business_value: str = "Medium"  # High, Medium, Low
    revenue_impact: float = 0.0  # Monthly revenue at risk in USD
    migration_complexity: str = "Medium"  # High, Medium, Low
    base_cost: float = 10000.0  # Estimated cost of migrating this service
    base_duration: int = 14  # Duration in days
    status: str = "Legacy"  # Legacy, Migrated, Discovered, Orphan
    failure_probability: float = 0.0  # Computed failure likelihood
    runtime: Optional[str] = "Unknown"
    annual_cost: float = 0.0

class DependencyEdge(BaseModel):
    source: str
    target: str
    type: str = "Sync"  # Sync, Async, DB, MQ
    criticality: str = "Medium"  # High, Medium, Low
    is_discovered: bool = False

class GraphData(BaseModel):
    nodes: List[ServiceNode]
    edges: List[DependencyEdge]

class UploadResponse(BaseModel):
    status: str
    parsed_nodes_count: int
    parsed_edges_count: int
    skipped_count: int = 0
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    message: str

class SimulationRequest(BaseModel):
    target_id: str
    already_migrated: List[str] = Field(default_factory=list)

class MonteCarloPoint(BaseModel):
    percentile: int
    duration_days: float
    cost_usd: float

class MonteCarloResult(BaseModel):
    confidence_90_duration: tuple[float, float]
    confidence_90_cost: tuple[float, float]
    expected_duration: float
    expected_cost: float
    distribution: List[Dict[str, Any]]  # List of records for charting probability curves

class SimulationResponse(BaseModel):
    impacted_services: List[ServiceNode]
    critical_paths: List[List[str]]
    revenue_at_risk: float
    total_impacted_services: int
    monte_carlo: MonteCarloResult
    total_hosting_cost: float = 0.0
    potential_savings: float = 0.0

class PlanningResponse(BaseModel):
    waves: List[List[str]]
    decoupling_strategies: List[Dict[str, Any]]
    negotiation_logs: List[Dict[str, Any]]
    risk_assessment: Dict[str, Any]
    trace_id: Optional[str] = None
    observability_summary: Optional[Dict[str, Any]] = None

class AgentStepResult(BaseModel):
    """Per-agent-step envelope, matching the Master Orchestrator spec's step-level output format."""
    current_agent: str
    status: str
    next_agent: str
    summary: str
    confidence: float = 0.0
    state_updates: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class AssessmentReport(BaseModel):
    """Final completion envelope for the full 12-agent Master Orchestrator pipeline."""
    assessment_summary: Dict[str, Any] = Field(default_factory=dict)
    migration_readiness: Dict[str, Any] = Field(default_factory=dict)
    complexity: Dict[str, Any] = Field(default_factory=dict)
    risk: Dict[str, Any] = Field(default_factory=dict)
    cloud_recommendation: Dict[str, Any] = Field(default_factory=dict)
    migration_plan: Dict[str, Any] = Field(default_factory=dict)
    simulation_results: Dict[str, Any] = Field(default_factory=dict)
    recommendation: Dict[str, Any] = Field(default_factory=dict)
    explainability: Dict[str, Any] = Field(default_factory=dict)
    report: Dict[str, Any] = Field(default_factory=dict)
    execution_history: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    status: str = "COMPLETED"


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]

class ChatResponse(BaseModel):
    reply: str
    trace_id: Optional[str] = None
