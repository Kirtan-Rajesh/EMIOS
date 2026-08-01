"""Unit tests for app.core.llm_provider.invoke_agentic() - the tool_use loop that
lets Bedrock-backed agents call a tool (see app/agents/tools.py) partway through a
completion instead of answering from static prompt context alone. No real network
calls: BedrockProvider instances here are constructed via __new__() (skipping
__init__'s real boto3 list_foundation_models() check) with a fake `_runtime` client
standing in for boto3's bedrock-runtime client.
"""

from typing import Any, Dict, List, Optional

import pytest

from app.core import constants
from app.core.llm_provider import BedrockProvider, LLMProvider, invoke_agentic


def _make_bedrock_provider(runtime) -> BedrockProvider:
    provider = BedrockProvider.__new__(BedrockProvider)
    provider._runtime = runtime
    return provider


class _FakeBedrockRuntime:
    """Stands in for boto3's bedrock-runtime client - `responses` is popped in
    order for each converse() call; a callable is invoked instead of popping,
    for tests that need an unbounded/dynamic sequence of responses."""

    def __init__(self, responses):
        self._responses = responses
        self.calls: List[Dict[str, Any]] = []

    def converse(self, **kwargs):
        # invoke_agentic's loop mutates its `messages` list in place across
        # iterations (see app.core.llm_provider._run_bedrock_tool_loop) - snapshot
        # a shallow copy here so a later call's calls[i]["messages"] doesn't
        # retroactively reflect appends made after this call already returned.
        snapshot = {**kwargs, "messages": list(kwargs.get("messages", []))}
        self.calls.append(snapshot)
        if callable(self._responses):
            return self._responses(len(self.calls))
        return self._responses[len(self.calls) - 1]


def _tool_use_response(tool_use_id: str, query: str = "order service") -> Dict[str, Any]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": tool_use_id, "name": "search_schema_graph", "input": {"query": query}}}
                ],
            }
        },
        "stopReason": "tool_use",
    }


def _end_turn_response(text: str) -> Dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
    }


_TOOL_SPEC = {"toolSpec": {"name": "search_schema_graph", "description": "test tool", "inputSchema": {"json": {}}}}


def test_immediate_end_turn_returns_text_without_calling_tool(monkeypatch):
    runtime = _FakeBedrockRuntime([_end_turn_response("No tool needed, here's the answer.")])
    provider = _make_bedrock_provider(runtime)
    monkeypatch.setattr("app.core.llm_provider.get_llm_providers", lambda: [provider])

    tool_calls = []
    result = invoke_agentic(
        "system", "user", _TOOL_SPEC, lambda name, inp: tool_calls.append((name, inp)) or "unused",
        "Test Agent", "fallback",
    )

    assert result == "No tool needed, here's the answer."
    assert tool_calls == []
    assert len(runtime.calls) == 1


def test_tool_use_then_end_turn_invokes_executor_and_returns_final_text(monkeypatch):
    runtime = _FakeBedrockRuntime([
        _tool_use_response("tool-1", query="order service"),
        _end_turn_response("Based on the search, Order Service depends on the Orders database."),
    ])
    provider = _make_bedrock_provider(runtime)
    monkeypatch.setattr("app.core.llm_provider.get_llm_providers", lambda: [provider])

    tool_calls = []

    def _executor(name: str, tool_input: Dict[str, Any]) -> str:
        tool_calls.append((name, tool_input))
        return "Order Service depends on the Orders database."

    result = invoke_agentic("system", "user", _TOOL_SPEC, _executor, "Test Agent", "fallback")

    assert result == "Based on the search, Order Service depends on the Orders database."
    assert tool_calls == [("search_schema_graph", {"query": "order service"})]
    assert len(runtime.calls) == 2
    # Second round-trip's messages must include the tool result keyed to the same toolUseId.
    second_call_messages = runtime.calls[1]["messages"]
    tool_result_message = second_call_messages[-1]
    assert tool_result_message["content"][0]["toolResult"]["toolUseId"] == "tool-1"
    assert tool_result_message["content"][0]["toolResult"]["content"][0]["text"] == "Order Service depends on the Orders database."


def test_exceeding_iteration_cap_falls_back(monkeypatch):
    # Always asks for another tool call - never reaches end_turn - so the loop
    # should give up after constants.AGENT_TOOL_MAX_ITERATIONS rounds and degrade
    # to the plain (non-tool) provider chain, which here also fails (the fake
    # runtime's response has no "text" content for BedrockProvider.invoke() to
    # read), landing on fallback_response.
    runtime = _FakeBedrockRuntime(lambda call_count: _tool_use_response(f"tool-{call_count}"))
    provider = _make_bedrock_provider(runtime)
    monkeypatch.setattr("app.core.llm_provider.get_llm_providers", lambda: [provider])

    tool_call_count = [0]

    def _executor(name: str, tool_input: Dict[str, Any]) -> str:
        tool_call_count[0] += 1
        return "some result"

    result = invoke_agentic("system", "user", _TOOL_SPEC, _executor, "Test Agent", "fallback response")

    assert result == "fallback response"
    assert tool_call_count[0] == constants.AGENT_TOOL_MAX_ITERATIONS


def test_no_bedrock_provider_degrades_to_plain_chain(monkeypatch):
    class _FakeGenericProvider(LLMProvider):
        name = "fake"

        def invoke(self, system_prompt: str, user_prompt: str, max_tokens: Optional[int] = None) -> str:
            return "plain completion, no tools"

    monkeypatch.setattr("app.core.llm_provider.get_llm_providers", lambda: [_FakeGenericProvider()])

    tool_calls = []
    result = invoke_agentic(
        "system", "user", _TOOL_SPEC, lambda name, inp: tool_calls.append((name, inp)) or "unused",
        "Test Agent", "fallback",
    )

    assert result == "plain completion, no tools"
    assert tool_calls == []


def test_no_providers_at_all_returns_fallback(monkeypatch):
    monkeypatch.setattr("app.core.llm_provider.get_llm_providers", lambda: [])

    result = invoke_agentic("system", "user", _TOOL_SPEC, lambda name, inp: "unused", "Test Agent", "fallback text")

    assert result == "fallback text"


def test_tool_executor_exception_is_fed_back_as_tool_result_not_raised(monkeypatch):
    runtime = _FakeBedrockRuntime([
        _tool_use_response("tool-1"),
        _end_turn_response("Handled the tool failure gracefully."),
    ])
    provider = _make_bedrock_provider(runtime)
    monkeypatch.setattr("app.core.llm_provider.get_llm_providers", lambda: [provider])

    def _broken_executor(name: str, tool_input: Dict[str, Any]) -> str:
        raise RuntimeError("boom")

    result = invoke_agentic("system", "user", _TOOL_SPEC, _broken_executor, "Test Agent", "fallback")

    assert result == "Handled the tool failure gracefully."
    second_call_messages = runtime.calls[1]["messages"]
    tool_result_text = second_call_messages[-1]["content"][0]["toolResult"]["content"][0]["text"]
    assert "boom" in tool_result_text
