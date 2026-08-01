class EMIOSException(Exception):
    """Base exception for all EMIOS platform failures."""
    def __init__(self, message: str, error_code: str = "EMIOS_INTERNAL_ERROR"):
        super().__init__(message)
        self.message = message
        self.error_code = error_code

class DatabaseConnectionException(EMIOSException):
    """Raised when database connections (Neo4j, Qdrant) time out or fail."""
    def __init__(self, message: str):
        super().__init__(message, error_code="DATABASE_CONNECTION_ERROR")

class InvalidIngestionException(EMIOSException):
    """Raised when CSV or JSON metadata fails mapping validation."""
    def __init__(self, message: str):
        super().__init__(message, error_code="INVALID_METADATA_FORMAT")

class SimulationException(EMIOSException):
    """Raised when cascading risk or Monte Carlo engines encounter failure."""
    def __init__(self, message: str):
        super().__init__(message, error_code="SIMULATION_PROCESSING_ERROR")

class WorkflowException(EMIOSException):
    """Raised when LangGraph Multi-Agent coordination flow fails."""
    def __init__(self, message: str):
        super().__init__(message, error_code="AGENTIC_WORKFLOW_ERROR")
