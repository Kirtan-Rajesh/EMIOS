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

class ResourceNotFoundException(EMIOSException):
    """Raised by the /api/v1 persistence layer when a requested record (assessment,
    upload, wave, ...) does not exist. Rendered as HTTP 404 - see the dedicated
    exception handler registered in main.py."""
    def __init__(self, message: str):
        super().__init__(message, error_code="RESOURCE_NOT_FOUND")
        self.status_code = 404

class DuplicateResourceException(EMIOSException):
    """Raised by the /api/v1 persistence layer when a create request would violate
    a uniqueness constraint (e.g. a duplicate wave_number for an assessment, or a
    duplicate email at registration). Rendered as HTTP 409 - see the dedicated
    exception handler registered in main.py."""
    def __init__(self, message: str):
        super().__init__(message, error_code="DUPLICATE_RESOURCE")
        self.status_code = 409

class UnauthorizedException(EMIOSException):
    """Raised by the /api/v1 auth layer (app/dependencies/auth.py, auth endpoints)
    when credentials are missing/invalid/expired, or a protected endpoint is called
    without a valid session. Rendered as HTTP 401 - see the dedicated exception
    handler registered in main.py."""
    def __init__(self, message: str):
        super().__init__(message, error_code="UNAUTHORIZED")
        self.status_code = 401

class BadRequestException(EMIOSException):
    """Raised by the /api/v1 persistence layer when a request is well-formed but
    violates a business precondition (e.g. running a simulation before a graph has
    been posted, or generating a report before a simulation has been run).
    Rendered as HTTP 400 - see the dedicated exception handler registered in main.py."""
    def __init__(self, message: str):
        super().__init__(message, error_code="BAD_REQUEST")
        self.status_code = 400
