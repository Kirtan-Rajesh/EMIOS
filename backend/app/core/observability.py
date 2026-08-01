import logging
import threading
import uuid
from typing import Optional, Dict, Any, Tuple

from app.core.config import settings

logger = logging.getLogger("emios")

# Global counters for telemetry, exposed via GET /api/observability/status.
trace_metrics = {
    "total_traces": 0,
    "total_generations": 0,
    "total_tokens_estimated": 0,
    "last_trace_id": None,
    "langfuse_status": "initialized"
}

try:
    from langfuse import Langfuse
    HAS_LANGFUSE = True
except ImportError:
    HAS_LANGFUSE = False
    logger.info("Langfuse SDK not installed. Tracing will operate in local metric fallback mode.")

# A single process-wide Langfuse client, built lazily on first use and reused
# for the life of the process - each Langfuse() instance owns its own
# background flush thread and HTTP connection pool, so constructing one per
# create_agent_trace()/record_generation() call (as this module used to)
# leaked a thread per LLM call and never actually delivered events, since
# nothing was ever flushed before the short-lived client was discarded.
_client: Optional[Any] = None
_client_init_attempted = False
_client_lock = threading.Lock()


def get_langfuse_client() -> Optional[Any]:
    """Returns the singleton Langfuse client, or None if tracing is disabled,
    the SDK isn't installed, or client construction failed. Safe to call from
    any request/thread - construction happens at most once."""
    global _client, _client_init_attempted

    if not HAS_LANGFUSE or not settings.ENABLE_LANGFUSE_TRACING:
        return None
    if _client_init_attempted:
        return _client

    with _client_lock:
        if _client_init_attempted:
            return _client
        _client_init_attempted = True
        try:
            _client = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
                # Without this, an unreachable/misconfigured LANGFUSE_HOST hangs
                # on the SDK's own default HTTP timeout - and get_prompt_text()
                # below calls out to it on every single prompt access (system +
                # user prompt, per agent), so that default compounds into
                # minutes across a multi-agent run instead of failing fast and
                # falling back to the hardcoded prompt text/no-op tracing, same
                # as "tracing disabled" already does.
                timeout=5,
            )
            trace_metrics["langfuse_status"] = "connected"
            logger.info(f"Langfuse client initialized against {settings.LANGFUSE_HOST}")
        except Exception as e:
            logger.warning(f"Could not initialize Langfuse client ({settings.LANGFUSE_HOST}): {e}")
            trace_metrics["langfuse_status"] = f"error: {e}"
            _client = None

    return _client


def _phase_span_id(assessment_id: str, phase: str) -> str:
    return f"span-{phase}-{assessment_id}"


def ensure_assessment_trace(
    assessment_id: str,
    name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    input_payload: Optional[Any] = None,
) -> None:
    """Upserts THE one Langfuse trace for this assessment (id == assessment_id,
    so every call site referring to the same assessment lands on the same
    trace with no lookup table needed - Langfuse merges repeated `trace(id=...)`
    calls for the same id rather than creating duplicates). Safe to call at any
    point in the assessment's lifecycle (creation, upload, agent run, report
    generation); each call only needs to pass whatever's new/relevant."""
    client = get_langfuse_client()
    if not client:
        return
    try:
        client.trace(
            id=assessment_id,
            name=name or f"Assessment {assessment_id}",
            metadata=metadata,
            input=input_payload,
        )
    except Exception as ex:
        logger.debug(f"Langfuse assessment trace upsert skipped: {ex}")


def _ensure_phase_span(assessment_id: str, phase: str, name: str, input_payload: Optional[Any] = None) -> Optional[str]:
    """Upserts one of the assessment's three sub-traces ('User Input', 'Agent
    Flow', 'Report') as a Langfuse span nested under ensure_assessment_trace()'s
    trace, keyed by a deterministic id so repeated calls (e.g. one per agent,
    or one per uploaded file) accumulate under the same span rather than each
    creating a new one. Returns the span id to nest further observations under
    it (via `parent_observation_id`), or None if tracing is unavailable."""
    client = get_langfuse_client()
    if not client:
        return None
    ensure_assessment_trace(assessment_id)
    span_id = _phase_span_id(assessment_id, phase)
    try:
        client.span(
            id=span_id,
            trace_id=assessment_id,
            name=name,
            input=input_payload,
        )
    except Exception as ex:
        logger.debug(f"Langfuse '{name}' span upsert skipped: {ex}")
    return span_id


def record_assessment_created(assessment_id: str, customer_name: str, project_name: str, target_cloud: str) -> None:
    """Seeds the assessment's trace and its 'User Input' sub-trace with the
    fields captured at assessment creation - paired with
    record_document_uploaded() below, which adds each uploaded file as a child
    event of the same 'User Input' span."""
    details = {"customer_name": customer_name, "project_name": project_name, "target_cloud": target_cloud}
    ensure_assessment_trace(assessment_id, name=f"Assessment: {customer_name} / {project_name}", input_payload=details)
    _ensure_phase_span(assessment_id, "user-input", "User Input", input_payload=details)


def record_document_uploaded(assessment_id: str, filename: str, content_type: Optional[str], source_type: str) -> None:
    """Adds one uploaded file as a child event under this assessment's 'User
    Input' span - called once per file (including once per member of a zip
    archive), so the span shows every document behind this assessment."""
    client = get_langfuse_client()
    if not client:
        return
    span_id = _ensure_phase_span(assessment_id, "user-input", "User Input")
    try:
        client.event(
            trace_id=assessment_id,
            parent_observation_id=span_id,
            name="File Uploaded",
            input={"filename": filename, "content_type": content_type, "source_type": source_type},
        )
    except Exception as ex:
        logger.debug(f"Langfuse file-upload event skipped: {ex}")


def create_agent_trace(
    agent_name: str,
    input_payload: Dict[str, Any],
    assessment_id: str = "",
    trace_phase: str = "agent",
) -> Tuple[str, Optional[str]]:
    """Returns (trace_id, parent_observation_id) for one LLM call's Langfuse
    trace/generation. When `assessment_id` is set, this nests the call under
    that assessment's single trace, inside its 'Agent Flow' or 'Report'
    sub-trace (per `trace_phase`) - so every agent/report LLM call for one
    assessment shows up grouped under that one assessment, instead of each
    call getting its own disconnected top-level trace. `assessment_id=""`
    (the legacy global-graph /api/plan, /api/assess, and copilot chat callers,
    which have no assessment to group by) keeps the original behavior: a
    brand-new independent trace per call."""
    trace_metrics["total_traces"] += 1

    if assessment_id:
        span_name = "Report" if trace_phase == "report" else "Agent Flow"
        span_id = _ensure_phase_span(assessment_id, trace_phase, span_name, input_payload=None)
        trace_metrics["last_trace_id"] = assessment_id
        return assessment_id, span_id

    trace_id = f"trace-{uuid.uuid4().hex[:12]}"
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

    return trace_id, None


def record_generation(
    trace_id: str,
    agent_name: str,
    prompt_text: str,
    output_text: str,
    model_name: str = "unknown",
    prompt_client: Optional[Any] = None,
    parent_observation_id: Optional[str] = None,
) -> None:
    """Records one LLM call as a Langfuse generation nested under `trace_id`
    (and, when given, further nested under `parent_observation_id` - one of
    the three per-assessment sub-trace spans created by create_agent_trace()).
    `prompt_client` is the TextPromptClient returned by get_prompt_text()'s
    Langfuse fetch (if any) - passing it links this generation to the exact
    prompt version that produced it, visible in the Langfuse UI."""
    trace_metrics["total_generations"] += 1
    est_tokens = len(prompt_text.split()) + len(output_text.split())
    trace_metrics["total_tokens_estimated"] += est_tokens

    client = get_langfuse_client()
    if client:
        try:
            generation = client.generation(
                name=f"Generation: {agent_name}",
                trace_id=trace_id,
                parent_observation_id=parent_observation_id,
                model=model_name,
                input=prompt_text,
                output=output_text,
                usage_details={"input": len(prompt_text.split()), "output": len(output_text.split()), "total": est_tokens},
                prompt=prompt_client,
            )
            generation.end(output=output_text)
        except Exception as ex:
            logger.debug(f"Langfuse generation logging skipped: {ex}")


def get_prompt_text(name: str, fallback_text: str) -> str:
    """Resolves `name` (a Langfuse prompt, `production` label) to its current
    managed text, or `fallback_text` unchanged if Langfuse tracing is
    disabled/unreachable or that prompt hasn't been created yet. The SDK
    caches successful fetches for 60s, so this is cheap to call on every
    prompt access (see app/agents/prompts.py's module __getattr__) rather
    than only once at import time - edits made in the Langfuse UI take
    effect for new LLM calls within a minute, no redeploy needed."""
    client = get_langfuse_client()
    if not client:
        return fallback_text
    try:
        return get_prompt_client(name, fallback_text).prompt
    except Exception as ex:
        logger.debug(f"Langfuse prompt fetch skipped for '{name}': {ex}")
        return fallback_text


def get_prompt_client(name: str, fallback_text: str) -> Optional[Any]:
    """Like get_prompt_text(), but returns the Langfuse TextPromptClient
    itself (or None if tracing is unavailable) so callers can pass it to
    record_generation()'s `prompt_client` for version linking."""
    client = get_langfuse_client()
    if not client:
        return None
    try:
        return client.get_prompt(name, fallback=fallback_text)
    except Exception as ex:
        logger.debug(f"Langfuse prompt fetch skipped for '{name}': {ex}")
        return None


def flush() -> None:
    """Blocks until any queued Langfuse events (traces/generations) are sent.
    Langfuse batches and sends events on a background thread, so anything
    queued right before process exit (FastAPI shutdown, a one-off script)
    would otherwise be silently dropped without this."""
    if _client is not None:
        try:
            _client.flush()
        except Exception as ex:
            logger.debug(f"Langfuse flush skipped: {ex}")


def get_observability_status() -> Dict[str, Any]:
    return {
        "status": "online" if settings.ENABLE_LANGFUSE_TRACING else "disabled",
        "langfuse_host": settings.LANGFUSE_HOST,
        "is_self_hosted": "cloud.langfuse.com" not in settings.LANGFUSE_HOST,
        "sdk_installed": HAS_LANGFUSE,
        "metrics": trace_metrics
    }
