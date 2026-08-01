import logging
import logging.handlers
import os
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
        # Structured log format: timestamp | level | logger | message
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # Standard stream handler pointing to stdout - what you see when running
        # `python main.py`/`uvicorn` directly in a terminal.
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        # Rotating file handler under backend/logs/emios.log - console scrollback
        # is easy to lose (terminal closed, container restarted, reload loop), and
        # this project has no separate log aggregation, so a failure that happened
        # "just now, no one was watching the console" would otherwise leave no
        # trace at all. 5MB x 3 backups is plenty for a hackathon-scale deployment.
        try:
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
            os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                os.path.join(log_dir, "emios.log"), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as e:
            # Don't let an unwritable log directory (permissions, read-only
            # filesystem) prevent the app from starting - console logging above
            # still works either way.
            logger.warning(f"Could not set up file logging: {e}")

    # Suppress verbose Uvicorn access logs slightly if needed
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    logger.info("Structured enterprise logger initialized successfully.")
