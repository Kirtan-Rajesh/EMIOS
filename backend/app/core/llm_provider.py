"""LLM provider abstraction: AWS Bedrock (preferred, per the AWS deployment
target) with the existing OpenAI/Gemini/Azure OpenAI options kept as configured
fallbacks - same priority-chain, degrade-gracefully pattern used for
Neo4j/Qdrant/S3 elsewhere in app/core.

Each provider implements the same invoke(system_prompt, user_prompt) -> str
interface. invoke_with_fallback() tries each configured provider in priority
order until one succeeds, falling through to a caller-supplied deterministic
fallback if none do - callers never need to know which provider (if any)
actually answered. Used by app/agents/workflow.py's execute_llm_prompt() (the
agent pipeline) and directly by any other one-off LLM call site, e.g.
app/services_v1/report_service.py's final migration-plan generation.
"""

from __future__ import annotations

import abc
import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core import constants, observability
from app.core.config import get_boto3_client, settings

logger = logging.getLogger("emios")

# Collapses runaway character repetition (e.g. a model drawing a horizontal
# rule and glitching into thousands of repeats of the same character) down to
# a harmless short run. This is a real, observed failure mode - not
# hypothetical - and it's expensive twice over: it eats the generation's
# entire token budget (directly adding to request latency), and it can
# corrupt the JSON envelope agent prompts ask for (an unterminated string
# hitting BEDROCK_MAX_TOKENS mid-repetition never gets a closing brace, so
# json.loads() fails and the raw, broken text - the wall of repeated
# characters - is what a caller falls back to showing). Applied to every
# provider's output unconditionally: no legitimate response needs the same
# character 8+ times in a row (even a deliberate "----------" divider reads
# identically collapsed to "---"), so this can never lose real content.
_PATHOLOGICAL_REPETITION_RE = re.compile(r"(.)\1{7,}")


def _collapse_pathological_repetition(text: str) -> str:
    return _PATHOLOGICAL_REPETITION_RE.sub(lambda m: m.group(1) * 3, text)


# Same rationale as _strip_decorative_unicode below: prompt instructions alone
# don't reliably stop a model from reaching for em dashes as its default
# sentence-connector, so this makes the outcome deterministic. " - " (a plain
# hyphen with surrounding spaces) reads naturally in place of an em dash used
# this way and matches the hyphen this module already substitutes for a
# stripped bullet character above. Collapses "a — b" and "a—b" alike, and
# tidies up if a stripped em dash lands next to a space that would otherwise
# double up.
_EM_DASH_RE = re.compile(r"\s*—\s*")


def _replace_em_dash(text: str) -> str:
    return _EM_DASH_RE.sub(" - ", text)


# Strips decorative Unicode (box/tree-drawing separators, block-shading
# characters, emoji, dingbat-style checkmarks/warnings) regardless of what
# the model does - prompt instructions asking the model not to use these
# (app/agents/prompts.py) measurably reduced but did not eliminate them: some
# agent narratives still come back full of tree-drawn diagrams (├─, └─, ═══)
# and emoji (📊 🚀 ✅ ⚠️) despite an explicit, repeated instruction not to.
# Relying on the model to reliably follow a style constraint across a dozen
# different prompts doesn't hold up in practice, so this makes the outcome
# deterministic instead of hopeful: every one of these characters is purely
# decorative (never load-bearing content - a risk score, a service name, a
# recommendation is never conveyed *by* a box-drawing character), so removing
# them can't lose real information. Applied before JSON parsing too - none of
# these ranges overlap JSON's own structural characters ({}[]":,), so this
# never corrupts a real JSON envelope.
_DECORATIVE_UNICODE_RE = re.compile(
    "["
    "─-╿"  # Box Drawing (─ │ ┌ ┐ └ ┘ ├ ┤ ┬ ┴ ┼ ═ ║ ╔ ╗ ╚ ╝ ...)
    "▀-▟"  # Block Elements (▓ ▒ ░ ...)
    "■-◿"  # Geometric Shapes (■ ▸ ● ...)
    "☀-➿"  # Misc Symbols + Dingbats (✓ ✗ ⚠ ★ ☑ ✅ ❌ ...)
    "\U0001f300-\U0001faff"  # Emoji (pictographs, transport, symbols, supplemental)
    "️"  # Variation Selector-16 (forces emoji-style rendering of the char before it)
    "‍"  # Zero-Width Joiner (glues compound emoji together)
    "]"
)
# A line consisting of nothing but decorative characters/whitespace is a pure
# divider ("═══", "├───┼───┤") - drop the whole line rather than leaving a
# meaningless bare "-" bullet behind.
_DIVIDER_LINE_RE = re.compile(r"^[ \t]*(?:" + _DECORATIVE_UNICODE_RE.pattern + r"|[ \t])+$", re.MULTILINE)


def _strip_decorative_unicode(text: str) -> str:
    # A stripped character at the very start of a line (that isn't a pure
    # divider, handled above) was very likely acting as a bullet marker
    # (✓/⚠/▸/■ item lists are common) - replace those with a plain "-" so the
    # line keeps reading as a list item instead of losing its structure.
    # Mid-line occurrences (inline emoji, tree-drawing prefixes) are just
    # removed outright, then blank lines/trailing spaces left behind by
    # removed dividers are collapsed.
    text = _DIVIDER_LINE_RE.sub("", text)
    text = re.sub(r"^[ \t]*" + _DECORATIVE_UNICODE_RE.pattern + r"+[ \t]*", "- ", text, flags=re.MULTILINE)
    text = _DECORATIVE_UNICODE_RE.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

# One retry, on the SAME provider, before moving on - only for errors that
# look transient. Kept short: this runs inside a threadpool-offloaded call
# already (see agent_run_service.py's run_in_threadpool wrapping), so it adds
# latency to that one call, not blocking anything else, but shouldn't turn a
# genuinely-down provider into a long stall either.
_TRANSIENT_RETRY_DELAY_SECONDS = 1.5


def _is_transient(exc: Exception) -> bool:
    """Best-effort heuristic for whether retrying the SAME provider is likely
    to help - string-matched rather than importing each provider SDK's own
    exception hierarchy (botocore/openai/google-generativeai - four different
    libraries, no shared base). A false positive just costs one extra
    ~1.5s-delayed attempt; a false negative falls through to the next
    provider, which was already the pre-existing behavior - low-stakes either
    way, so this doesn't need to be exhaustive."""
    text = f"{type(exc).__name__} {exc}".lower()
    return any(
        kw in text
        for kw in ("timeout", "timed out", "connection", "throttl", "rate limit", "503", "429", "temporarily unavailable")
    )

_PLACEHOLDER_VALUES = {
    None, "", "mock_key_or_empty",
    "your_openai_api_key", "your_gemini_api_key", "your_azure_api_key",
}


def is_configured(value: Optional[str]) -> bool:
    return value not in _PLACEHOLDER_VALUES


class LLMProvider(abc.ABC):
    name: str = "unknown"

    @abc.abstractmethod
    def invoke(self, system_prompt: str, user_prompt: str, max_tokens: Optional[int] = None) -> str:
        """Returns completion text, or raises on failure - the caller catches
        and moves on to the next provider in the chain. `max_tokens`, when
        given, overrides settings.BEDROCK_MAX_TOKENS for just this call - the
        agent pipeline's short narrative responses need nowhere near the
        headroom the Document Discovery extraction prompts do (see
        app.agents.workflow.execute_llm_prompt), and a tighter cap there also
        bounds the worst case if a response starts degenerating into
        repetition instead of ending normally."""
        raise NotImplementedError


class BedrockProvider(LLMProvider):
    """Uses boto3's bedrock-runtime Converse API directly (not langchain-aws) -
    avoids adding another LangChain integration package that could conflict
    with the langchain-core<0.3.0 pin the existing OpenAI/Gemini integrations
    rely on. Constructor does a cheap `list_foundation_models` call (via the
    separate `bedrock` client, not `bedrock-runtime`) to verify credentials/
    region access without invoking - and billing for - an actual model, mirroring
    the verify-connectivity pattern used by Neo4j/Qdrant/S3 elsewhere."""

    name = "bedrock"
    # get_boto3_client()'s default 8s read timeout is tuned for the cheap
    # list_foundation_models() connectivity check below, not for actual text
    # generation - a full JSON extraction response (up to BEDROCK_MAX_TOKENS)
    # can legitimately take longer than that, and an 8s cutoff here was
    # observed silently failing ~27% of real Document Extraction Agent calls
    # (logged as a generic "provider failed" and treated identically to "not
    # configured" by invoke_with_fallback()).
    _INFERENCE_READ_TIMEOUT_SECONDS = 30

    def __init__(self):
        get_boto3_client("bedrock").list_foundation_models()
        self._runtime = get_boto3_client("bedrock-runtime", read_timeout=self._INFERENCE_READ_TIMEOUT_SECONDS)

    def invoke(self, system_prompt: str, user_prompt: str, max_tokens: Optional[int] = None) -> str:
        response = self._runtime.converse(
            modelId=settings.BEDROCK_LLM_MODEL_ID,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            inferenceConfig={
                "temperature": settings.LLM_TEMPERATURE,
                "maxTokens": max_tokens if max_tokens is not None else settings.BEDROCK_MAX_TOKENS,
            },
        )
        return response["output"]["message"]["content"][0]["text"]

    def invoke_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tool_spec: Dict[str, Any],
        max_tokens: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], str]:
        """One Converse API round-trip with `toolConfig` set - unlike invoke(), returns
        the raw assistant `message` dict and `stopReason` rather than plain text, so the
        caller (see invoke_agentic()'s tool_use loop below) can tell whether the model
        wants to call a tool or is done, and can append the message verbatim onto the
        conversation for the next round-trip. Only implemented on BedrockProvider - the
        Converse API is the one client already used here (no langchain-aws dependency,
        see the class docstring above); the LangChain-backed providers don't get this
        method, so invoke_agentic() only attempts tool use when Bedrock is the active
        provider and falls back to plain invoke() otherwise."""
        response = self._runtime.converse(
            modelId=settings.BEDROCK_LLM_MODEL_ID,
            system=[{"text": system_prompt}],
            messages=messages,
            toolConfig={"tools": [tool_spec]},
            inferenceConfig={
                "temperature": settings.LLM_TEMPERATURE,
                "maxTokens": max_tokens if max_tokens is not None else settings.BEDROCK_MAX_TOKENS,
            },
        )
        return response["output"]["message"], response["stopReason"]


class _LangChainChatProvider(LLMProvider):
    """Shared invoke() for the three existing LangChain-backed providers below -
    only construction differs per provider."""

    _llm = None

    def invoke(self, system_prompt: str, user_prompt: str, max_tokens: Optional[int] = None) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        llm = self._llm
        if max_tokens is not None:
            # Best-effort per-call override - not every LangChain chat model
            # honors max_tokens via .bind() identically, so a rejection here
            # just means this call runs at the provider's constructor-time
            # default rather than failing the whole request.
            try:
                llm = self._llm.bind(max_tokens=max_tokens)
            except Exception:
                llm = self._llm
        response = llm.invoke(messages)
        return response.content


class GeminiProvider(_LangChainChatProvider):
    name = "gemini"

    def __init__(self):
        from langchain_google_genai import ChatGoogleGenerativeAI

        self._llm = ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
        )

    def invoke(self, system_prompt: str, user_prompt: str, max_tokens: Optional[int] = None) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        # Unlike ChatOpenAI/AzureChatOpenAI, ChatGoogleGenerativeAI has no
        # constructor-level timeout field - request_options is the underlying
        # google-generativeai SDK's own per-call timeout mechanism, forwarded
        # through _generate()'s **kwargs. Without this, a hung Gemini request
        # blocks indefinitely (see BedrockProvider's own explicit timeout, the
        # one provider that already had this).
        call_kwargs: Dict[str, Any] = {"request_options": {"timeout": settings.LLM_REQUEST_TIMEOUT_SECONDS}}
        if max_tokens is not None:
            call_kwargs["generation_config"] = {"max_output_tokens": max_tokens}
        response = self._llm.invoke(messages, **call_kwargs)
        return response.content


class OpenAIProvider(_LangChainChatProvider):
    name = "openai"

    def __init__(self):
        from langchain_openai import ChatOpenAI

        self._llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        )


class AzureOpenAIProvider(_LangChainChatProvider):
    name = "azure_openai"

    def __init__(self):
        from langchain_openai import AzureChatOpenAI

        self._llm = AzureChatOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            deployment_name=settings.AZURE_OPENAI_DEPLOYMENT,
            openai_api_version=settings.AZURE_OPENAI_API_VERSION,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        )


_providers: Optional[List[LLMProvider]] = None


def get_llm_providers() -> List[LLMProvider]:
    """Returns configured providers in priority order (Bedrock first), memoized
    after the first call - same "connect once, reuse for the process lifetime"
    pattern as app.core.embeddings.get_embedding_provider(). Before this cache
    existed, every call reconstructed every provider from scratch, and
    BedrockProvider.__init__ makes a real list_foundation_models() network
    round-trip to verify credentials - with invoke_with_fallback() (and this
    function) called once per agent in the 12-14-agent wave-planner pipeline,
    that was 12-14 redundant Bedrock connectivity checks on top of the actual
    generation calls, on every single run. Each provider is still constructed
    lazily/best-effort so one bad config doesn't break the others - a provider
    that fails to construct is simply omitted (and, since the whole list is
    cached, not retried again this process - see reset_llm_provider_cache() for
    the test-only escape hatch)."""
    global _providers
    if _providers is not None:
        return _providers

    providers: List[LLMProvider] = []

    try:
        providers.append(BedrockProvider())
    except Exception as e:
        logger.debug(f"Bedrock LLM provider unavailable: {e}")

    if is_configured(settings.GEMINI_API_KEY):
        try:
            providers.append(GeminiProvider())
        except Exception as e:
            logger.debug(f"Gemini provider unavailable: {e}")

    if is_configured(settings.OPENAI_API_KEY):
        try:
            providers.append(OpenAIProvider())
        except Exception as e:
            logger.debug(f"OpenAI provider unavailable: {e}")

    if is_configured(settings.AZURE_OPENAI_API_KEY) and is_configured(settings.AZURE_OPENAI_ENDPOINT):
        try:
            providers.append(AzureOpenAIProvider())
        except Exception as e:
            logger.debug(f"Azure OpenAI provider unavailable: {e}")

    _providers = providers
    return providers


def reset_llm_provider_cache() -> None:
    """Test-only hook: clears the memoized provider list so tests can run
    without whatever real credentials happen to be configured in the process
    env - mirrors app.core.embeddings.reset_embedding_provider_cache()."""
    global _providers
    _providers = None


def _run_provider_chain(
    providers: List[LLMProvider],
    system_prompt: str,
    user_prompt: str,
    agent_name: str,
    fallback_response: str,
    trace_id: str,
    parent_observation_id: Optional[str],
    max_tokens: Optional[int],
) -> str:
    """Tries each of `providers` in order until one succeeds (with one retry on
    the SAME provider first for errors that look transient - see _is_transient);
    records the winning (or, if none succeed, the fallback) output as a Langfuse
    generation under the given trace. Shared by invoke_with_fallback() and
    invoke_agentic()'s no-tool-use path so both use the exact same single-shot
    completion behavior."""
    for provider in providers:
        for attempt in (1, 2):
            try:
                raw_output = provider.invoke(system_prompt, user_prompt, max_tokens=max_tokens)
                output_text = _strip_decorative_unicode(_replace_em_dash(_collapse_pathological_repetition(raw_output)))
                observability.record_generation(
                    trace_id, agent_name, user_prompt, output_text, model_name=provider.name, parent_observation_id=parent_observation_id
                )
                return output_text
            except Exception as ex:
                if attempt == 1 and _is_transient(ex):
                    logger.warning(
                        f"LLM provider '{provider.name}' hit a transient-looking error for {agent_name}, "
                        f"retrying once before moving on: {ex}"
                    )
                    time.sleep(_TRANSIENT_RETRY_DELAY_SECONDS)
                    continue
                logger.warning(f"LLM provider '{provider.name}' failed for {agent_name}, trying next: {ex}")
                break

    observability.record_generation(
        trace_id, agent_name, user_prompt, fallback_response, parent_observation_id=parent_observation_id
    )
    return fallback_response


def invoke_with_fallback(
    system_prompt: str,
    user_prompt: str,
    agent_name: str,
    fallback_response: str,
    assessment_id: str = "",
    trace_phase: str = "agent",
    max_tokens: Optional[int] = None,
) -> str:
    """Tries each configured provider (Bedrock first) until one succeeds;
    returns `fallback_response` if none do or none are configured. Traces via
    Langfuse either way (app.core.observability). `assessment_id`, when set,
    groups this call under that assessment's single Langfuse trace instead of
    a disconnected one-off trace - see create_agent_trace()'s docstring.
    `trace_phase` picks which of that assessment's sub-traces this call
    belongs under: "agent" (the Discovery/Dependency/.../Report agent
    pipeline) or "report" (app/services_v1/report_service.py's narrative/
    revision calls). `max_tokens` overrides settings.BEDROCK_MAX_TOKENS for
    just this call - see LLMProvider.invoke()'s docstring for why."""
    trace_id, parent_observation_id = observability.create_agent_trace(
        agent_name, {"system": system_prompt, "user": user_prompt}, assessment_id=assessment_id, trace_phase=trace_phase
    )
    return _run_provider_chain(
        get_llm_providers(), system_prompt, user_prompt, agent_name, fallback_response,
        trace_id, parent_observation_id, max_tokens,
    )


def _run_bedrock_tool_loop(
    provider: BedrockProvider,
    system_prompt: str,
    user_prompt: str,
    tool_spec: Dict[str, Any],
    tool_executor: Callable[[str, Dict[str, Any]], str],
    max_tokens: Optional[int],
) -> str:
    """Drives the Converse API tool_use protocol to completion: calls
    provider.invoke_with_tools(), and whenever the model's stopReason is "tool_use",
    runs `tool_executor(tool_name, tool_input)` and feeds the result back in as a
    toolResult message before calling again - up to constants.AGENT_TOOL_MAX_ITERATIONS
    rounds. Raises (rather than returning a degraded answer) if that cap is hit without
    the model reaching "end_turn", so invoke_agentic()'s caller falls back to a plain
    non-tool completion instead of surfacing a half-finished tool-loop result."""
    messages: List[Dict[str, Any]] = [{"role": "user", "content": [{"text": user_prompt}]}]

    for _ in range(constants.AGENT_TOOL_MAX_ITERATIONS):
        message, stop_reason = provider.invoke_with_tools(system_prompt, messages, tool_spec, max_tokens=max_tokens)
        messages.append(message)

        tool_use_blocks = [block["toolUse"] for block in message.get("content", []) if "toolUse" in block]
        if stop_reason != "tool_use" or not tool_use_blocks:
            return "".join(block["text"] for block in message.get("content", []) if "text" in block)

        result_content = []
        for tool_use in tool_use_blocks:
            try:
                result_text = tool_executor(tool_use["name"], tool_use.get("input", {}))
            except Exception as ex:
                result_text = f"Tool execution failed: {ex}"
            result_content.append(
                {"toolResult": {"toolUseId": tool_use["toolUseId"], "content": [{"text": result_text}]}}
            )
        messages.append({"role": "user", "content": result_content})

    raise RuntimeError(f"Bedrock tool loop exceeded {constants.AGENT_TOOL_MAX_ITERATIONS} iterations without finishing")


def invoke_agentic(
    system_prompt: str,
    user_prompt: str,
    tool_spec: Dict[str, Any],
    tool_executor: Callable[[str, Dict[str, Any]], str],
    agent_name: str,
    fallback_response: str,
    assessment_id: str = "",
    trace_phase: str = "agent",
    max_tokens: Optional[int] = None,
) -> str:
    """Like invoke_with_fallback(), but lets the model call a tool (`tool_spec`,
    executed via `tool_executor(tool_name, tool_input) -> str`) partway through
    instead of answering from the prompt's static context alone.

    Tool use only runs when Bedrock (the preferred provider, see BedrockProvider's
    docstring) is configured and reachable - its Converse API is the one client here
    that supports toolConfig natively. If Bedrock isn't available, or a tool-enabled
    call raises for any reason (model doesn't support tools, malformed tool output,
    the iteration cap in _run_bedrock_tool_loop), this degrades to the exact same
    single-shot provider chain invoke_with_fallback() uses - no tool use, same
    fallback_response if nothing succeeds. Callers should build `system_prompt` and
    `user_prompt` exactly as they would for invoke_with_fallback(); only mention the
    tool's availability in the system prompt (see app/agents/prompts.py)."""
    trace_id, parent_observation_id = observability.create_agent_trace(
        agent_name, {"system": system_prompt, "user": user_prompt}, assessment_id=assessment_id, trace_phase=trace_phase
    )

    providers = get_llm_providers()
    bedrock_provider = next((p for p in providers if isinstance(p, BedrockProvider)), None)

    if bedrock_provider is not None:
        for attempt in (1, 2):
            try:
                raw_output = _run_bedrock_tool_loop(
                    bedrock_provider, system_prompt, user_prompt, tool_spec, tool_executor, max_tokens
                )
                output_text = _strip_decorative_unicode(_replace_em_dash(_collapse_pathological_repetition(raw_output)))
                observability.record_generation(
                    trace_id, agent_name, user_prompt, output_text,
                    model_name=bedrock_provider.name, parent_observation_id=parent_observation_id,
                )
                return output_text
            except Exception as ex:
                if attempt == 1 and _is_transient(ex):
                    logger.warning(
                        f"Bedrock tool-calling hit a transient-looking error for {agent_name}, "
                        f"retrying once before falling back to plain completion: {ex}"
                    )
                    time.sleep(_TRANSIENT_RETRY_DELAY_SECONDS)
                    continue
                logger.warning(f"Bedrock tool-calling failed for {agent_name}, falling back to plain completion: {ex}")
                break

    return _run_provider_chain(
        providers, system_prompt, user_prompt, agent_name, fallback_response,
        trace_id, parent_observation_id, max_tokens,
    )
