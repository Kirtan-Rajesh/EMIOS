import logging
import uuid
from typing import Optional, Dict, Any
from app.core.config import settings

logger = logging.getLogger("emios")

# Global counters for telemetry
trace_metrics = {
    "total_traces": 0,
    "total_generations": 0,
    "total_tokens_estimated": 0,
    "last_trace_id": None,
    "langfuse_status": "initialized"
}

# Try importing langfuse safely
try:
    from langfuse import Langfuse
    from langfuse.callback import CallbackHandler
    HAS_LANGFUSE = True
except ImportError:
    HAS_LANGFUSE = False
    logger.info("Langfuse SDK not installed. Tracing will operate in local metric fallback mode.")


def get_langfuse_client() -> Optional[Any]:
    if not HAS_LANGFUSE or not settings.ENABLE_LANGFUSE_TRACING:
        return None
    try:
        client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST
        )
        return client
    except Exception as e:
        logger.warning(f"Could not connect to Langfuse host ({settings.LANGFUSE_HOST}): {e}")
        return None


def get_langfuse_callback_handler(trace_name: str = "EMIOS_Agent_Workflow") -> Optional[Any]:
    if not HAS_LANGFUSE or not settings.ENABLE_LANGFUSE_TRACING:
        return None
    try:
        handler = CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
            trace_name=trace_name
        )
        return handler
    except Exception as e:
        logger.warning(f"Failed to create Langfuse CallbackHandler: {e}")
        return None


def create_agent_trace(agent_name: str, input_payload: Dict[str, Any]) -> str:
    trace_id = f"trace-{uuid.uuid4().hex[:12]}"
    trace_metrics["total_traces"] += 1
    trace_metrics["last_trace_id"] = trace_id
    
    client = get_langfuse_client()
    if client:
        try:
            client.trace(
                id=trace_id,
                name=f"Agent Execution: {agent_name}",
                metadata={"agent": agent_name, "host": settings.LANGFUSE_HOST},
                input=input_payload
            )
        except Exception as ex:
            logger.debug(f"Langfuse trace logging skipped: {ex}")
            
    return trace_id


def record_generation(trace_id: str, agent_name: str, prompt_text: str, output_text: str, model_name: str = "gpt-4o"):
    trace_metrics["total_generations"] += 1
    est_tokens = len(prompt_text.split()) + len(output_text.split())
    trace_metrics["total_tokens_estimated"] += est_tokens

    client = get_langfuse_client()
    if client:
        try:
            generation = client.generation(
                name=f"Generation: {agent_name}",
                trace_id=trace_id,
                prompt=prompt_text,
                completion=output_text,
                model=model_name,
                usage={"total_tokens": est_tokens}
            )
            generation.end()
        except Exception as ex:
            logger.debug(f"Langfuse generation logging skipped: {ex}")


def get_observability_status() -> Dict[str, Any]:
    return {
        "status": "online" if settings.ENABLE_LANGFUSE_TRACING else "disabled",
        "langfuse_host": settings.LANGFUSE_HOST,
        "is_self_hosted": "localhost" in settings.LANGFUSE_HOST or "127.0.0.1" in settings.LANGFUSE_HOST,
        "sdk_installed": HAS_LANGFUSE,
        "metrics": trace_metrics
    }
