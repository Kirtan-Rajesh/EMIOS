# Core Constants defining EMIOS simulation modifiers and agent thresholds

# In-Memory DB Config
DEFAULT_MIGRATION_STATUS = "Legacy"

# Cascading Risk Criticality Multipliers
CRITICALITY_FACTOR_HIGH = 0.8
CRITICALITY_FACTOR_MEDIUM = 0.4
CRITICALITY_FACTOR_LOW = 0.1

# Connection Type Modifiers
TYPE_MODIFIER_SYNC = 1.2
TYPE_MODIFIER_DB = 1.1
TYPE_MODIFIER_ASYNC_MQ = 0.5

# Monte Carlo Range Boundaries
MONTE_CARLO_MIN_DURATION_FACTOR = 0.9
MONTE_CARLO_MAX_DURATION_BASE = 1.1
MONTE_CARLO_MAX_DURATION_RISK_MULTIPLIER = 2.0

MONTE_CARLO_MIN_COST_FACTOR = 0.95
MONTE_CARLO_MAX_COST_BASE = 1.2
MONTE_CARLO_MAX_COST_RISK_MULTIPLIER = 2.5

# Multi-Agent Planner Thresholds
PLANNER_MAX_ITERATIONS = 5
PLANNER_RISK_THRESHOLD = 0.15  # Objections trigger if a node risk exceeds 15%
PLANNER_VIOLATION_COST_HIGH = 0.40
PLANNER_VIOLATION_COST_MEDIUM = 0.20
PLANNER_VIOLATION_COST_SYNC = 0.15

# Estimator Defaults
MIGRATION_COST_FACTOR = 1.2
MIGRATION_COST_MIN = 5000.0
REVENUE_MULTIPLIER = 10.0
MONTHS_IN_YEAR = 12.0
MIGRATION_DURATION_LOW = 14
MIGRATION_DURATION_MEDIUM = 30
MIGRATION_DURATION_HIGH = 90
CLOUD_SAVINGS_MULTIPLIER = 0.30

# --- Master Orchestrator: Complexity Assessment weights (0-1 contribution per dimension) ---
COMPLEXITY_WEIGHT_ARCHITECTURE = 0.25
COMPLEXITY_WEIGHT_BUSINESS = 0.15
COMPLEXITY_WEIGHT_TECHNOLOGY = 0.20
COMPLEXITY_WEIGHT_INTEGRATION = 0.25
COMPLEXITY_WEIGHT_MIGRATION = 0.15

# Complexity score -> engineering effort (person-days per complexity point) & team sizing
COMPLEXITY_EFFORT_DAYS_PER_POINT = 5.0
COMPLEXITY_TEAM_SIZE_DIVISOR = 90.0  # engineering days per additional team member
COMPLEXITY_TEAM_SIZE_MIN = 2

# --- Master Orchestrator: Cloud Readiness weights ---
CLOUD_READINESS_WEIGHT_COMPLEXITY = 0.4
CLOUD_READINESS_WEIGHT_RISK = 0.35
CLOUD_READINESS_WEIGHT_BUSINESS_VALUE = 0.25

# --- Master Orchestrator: Simulation strategy multipliers (cost_factor, duration_factor, risk_factor) ---
# risk_factor scales overall enterprise risk per strategy: Lift & Shift carries the legacy
# risk forward untouched (higher), Refactor addresses root causes (lower).
SIMULATION_STRATEGY_MULTIPLIERS = {
    "Lift & Shift": {"cost_factor": 0.7, "duration_factor": 0.6, "risk_factor": 1.3},
    "Replatform": {"cost_factor": 1.0, "duration_factor": 1.0, "risk_factor": 1.0},
    "Refactor": {"cost_factor": 1.6, "duration_factor": 1.8, "risk_factor": 0.7},
}

# --- Master Orchestrator: Conditional routing thresholds ---
SIMULATION_RISK_FORCE_ALL_THRESHOLD = 0.80
MODERNIZATION_READINESS_THRESHOLD = 0.60
AGENT_MAX_RETRIES = 1

# Caps how many tool_use round-trips app.core.llm_provider.invoke_agentic() will make
# per call before returning whatever text it has - bounds latency/cost if a model keeps
# calling search_schema_graph (app/agents/tools.py) instead of settling on an answer.
AGENT_TOOL_MAX_ITERATIONS = 3
