"""
LLM Tool-Calling Package for RecoverAI (Milestone 5).
"""

from agent.llm.base import (
    FailureCategory,
    LLMMessage,
    LLMResponse,
    LLMToolCall,
    LLMProvider,
)
from agent.llm.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT_V1,
    build_system_prompt,
    format_context_user_message,
    build_llm_messages,
)
from agent.llm.validator import ToolCallValidator, ToolValidationError, default_tool_validator
from agent.llm.model import LLMAgentModel
from agent.llm.providers import (
    MockLLMProvider,
    OpenAILLMProvider,
    AnthropicLLMProvider,
    GeminiLLMProvider,
)

__all__ = [
    "FailureCategory",
    "LLMMessage",
    "LLMResponse",
    "LLMToolCall",
    "LLMProvider",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT_V1",
    "build_system_prompt",
    "format_context_user_message",
    "build_llm_messages",
    "ToolCallValidator",
    "ToolValidationError",
    "default_tool_validator",
    "LLMAgentModel",
    "MockLLMProvider",
    "OpenAILLMProvider",
    "AnthropicLLMProvider",
    "GeminiLLMProvider",
]
