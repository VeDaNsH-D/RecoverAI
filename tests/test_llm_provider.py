"""
Unit tests for RecoverAI LLM Providers (Milestone 5).
Verifies MockLLMProvider deterministic reasoning, scripted sequences, timeouts, and error handling.
"""

import pytest
from agent.llm.base import LLMMessage, LLMResponse, LLMToolCall
from agent.llm.providers.mock_provider import MockLLMProvider
from agent.llm.providers.openai_provider import OpenAILLMProvider
from agent.llm.providers.anthropic_provider import AnthropicLLMProvider
from agent.llm.providers.gemini_provider import GeminiLLMProvider
from agent.tools.registry import default_tool_registry


def test_mock_provider_deterministic_autonomous_flow():
    """Verify MockLLMProvider autonomously emits correct tool calling sequence based on context."""
    provider = MockLLMProvider()
    tools = default_tool_registry.list_tools()

    # Step 1: Decision not obtained
    msgs_1 = [
        LLMMessage(role="system", content="System rules..."),
        LLMMessage(role="user", content="Case ID: case_001\nDecision ID: NONE\nAction ID: NONE"),
    ]
    resp_1 = provider.generate_tool_call(msgs_1, tools)
    assert len(resp_1.tool_calls) == 1
    assert resp_1.tool_calls[0].tool == "get_recovery_decision"
    assert resp_1.tool_calls[0].arguments == {"case_id": "case_001"}
    assert resp_1.total_tokens > 0
    assert resp_1.provider == "mock"

    # Step 2: Decision obtained, action not executed
    msgs_2 = [
        LLMMessage(role="system", content="System rules..."),
        LLMMessage(
            role="user",
            content="Case ID: case_001\nDecision ID: dec_123\nRecommended Action: retry\nAction ID: NONE\nCurrent Operational State: DECIDED",
        ),
    ]
    resp_2 = provider.generate_tool_call(msgs_2, tools)
    assert len(resp_2.tool_calls) == 1
    assert resp_2.tool_calls[0].tool == "execute_recovery_action"
    assert resp_2.tool_calls[0].arguments["action"] == "retry"
    assert resp_2.tool_calls[0].arguments["decision_id"] == "dec_123"

    # Step 3: Terminal state reached
    msgs_3 = [
        LLMMessage(role="system", content="System rules..."),
        LLMMessage(
            role="user",
            content="Case ID: case_001\nDecision ID: dec_123\nRecommended Action: retry\nAction ID: act_123\nCurrent Operational State: ACTION_EXECUTED",
        ),
    ]
    resp_3 = provider.generate_tool_call(msgs_3, tools)
    assert len(resp_3.tool_calls) == 0
    assert "complete" in resp_3.content.lower()


def test_mock_provider_scripted_calls():
    """Verify MockLLMProvider accurately executes custom scripted tool sequences."""
    script = [
        {"tool": "get_payment_case", "arguments": {"case_id": "case_scripted"}},
        {"tool": "get_recovery_decision", "arguments": {"case_id": "case_scripted"}},
    ]
    provider = MockLLMProvider(scripted_calls=script)
    tools = default_tool_registry.list_tools()

    resp_1 = provider.generate_tool_call([], tools)
    assert resp_1.tool_calls[0].tool == "get_payment_case"

    resp_2 = provider.generate_tool_call([], tools)
    assert resp_2.tool_calls[0].tool == "get_recovery_decision"

    resp_3 = provider.generate_tool_call([], tools)
    assert len(resp_3.tool_calls) == 0


def test_mock_provider_timeout_and_error_handling():
    """Verify MockLLMProvider timeout and error simulation."""
    timeout_provider = MockLLMProvider(force_timeout=True)
    with pytest.raises(TimeoutError) as exc_info:
        timeout_provider.generate_tool_call([], [])
    assert "timed out" in str(exc_info.value)

    err_provider = MockLLMProvider(force_provider_error="Rate limit exceeded (HTTP 429)")
    with pytest.raises(RuntimeError) as exc_info:
        err_provider.generate_tool_call([], [])
    assert "Rate limit exceeded" in str(exc_info.value)


def test_external_providers_missing_key_handling():
    """Verify external provider classes raise clear errors when API keys are unconfigured."""
    openai_prov = OpenAILLMProvider(api_key="")
    with pytest.raises(RuntimeError) as exc_openai:
        openai_prov.generate_tool_call([], [])
    assert "OPENAI_API_KEY" in str(exc_openai.value)

    anthropic_prov = AnthropicLLMProvider(api_key="")
    with pytest.raises(RuntimeError) as exc_anthropic:
        anthropic_prov.generate_tool_call([], [])
    assert "ANTHROPIC_API_KEY" in str(exc_anthropic.value)

    gemini_prov = GeminiLLMProvider(api_key="")
    with pytest.raises(RuntimeError) as exc_gemini:
        gemini_prov.generate_tool_call([], [])
    assert "GEMINI_API_KEY" in str(exc_gemini.value)
