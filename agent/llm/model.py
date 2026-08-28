"""
LLMAgentModel implementation for RecoverAI (Milestone 5).
Implements the AgentModel driver interface using structured tool calling and hard semantic validation.
"""

from typing import Any, Dict, List, Optional
from agent.models import AgentContext, AgentModel
from agent.llm.base import LLMProvider, FailureCategory, LLMToolCall
from agent.llm.providers.mock_provider import MockLLMProvider
from agent.llm.prompts import build_llm_messages, PROMPT_VERSION
from agent.llm.validator import ToolCallValidator, ToolValidationError, default_tool_validator


class LLMAgentModel(AgentModel):
    """
    LLM-driven AgentModel strategy for RecoverAI Recovery Agent.
    Interprets observable case context, prompts the LLM provider, and enforces strict semantic validation.
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        validator: Optional[ToolCallValidator] = None,
        prompt_version: str = PROMPT_VERSION,
        temperature: float = 0.0,
    ):
        self.provider = provider or MockLLMProvider()
        self.validator = validator or default_tool_validator
        self.prompt_version = prompt_version
        self.temperature = temperature
        self.last_response_metadata: Dict[str, Any] = {}

    def decide_next_tool(
        self,
        context: AgentContext,
        available_tools: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        # 1. Assemble messages
        messages = build_llm_messages(context, self.prompt_version)

        # 2. Invoke LLM Provider with error categorization
        try:
            response = self.provider.generate_tool_call(
                messages=messages,
                tools=available_tools,
                temperature=self.temperature,
            )
        except TimeoutError as exc:
            raise ToolValidationError(f"LLM Provider Timeout: {str(exc)}", category=FailureCategory.MODEL_ERROR) from exc
        except Exception as exc:
            raise ToolValidationError(f"LLM Provider Error: {str(exc)}", category=FailureCategory.MODEL_ERROR) from exc

        # Save metadata for telemetry/audit
        self.last_response_metadata = {
            "model": response.model,
            "provider": response.provider,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "latency_ms": response.latency_ms,
            "prompt_version": self.prompt_version,
        }

        # 3. Handle No-Tool / Terminal Case
        if not response.tool_calls:
            # Enforce that domain is in a legitimate terminal state
            self.validator.validate_workflow_completion(context)
            return None

        # 4. Extract and Validate First Tool Call
        raw_tool_call = response.tool_calls[0]
        self.validator.validate_tool_call(raw_tool_call, context)

        return {
            "tool": raw_tool_call.tool,
            "arguments": raw_tool_call.arguments,
            "metadata": self.last_response_metadata,
        }
