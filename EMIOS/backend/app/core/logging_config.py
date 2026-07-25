import logging
import sys

def setup_logging():
    """
    Configures structured, clean logging for the FastAPI application.
    Sets levels and output formatters globally.
    """
    logger = logging.getLogger("emios")
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if already initialized
    if not logger.handlers:
        # Standard stream handler pointing to stdout
        handler = logging.StreamHandler(sys.stdout)
        
        # Structured log format: timestamp | level | logger | message
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    # Suppress verbose Uvicorn access logs slightly if needed
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    logger.info("Structured enterprise logger initialized successfully.")
