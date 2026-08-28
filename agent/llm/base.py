"""
Base interfaces and schemas for RecoverAI LLM Tool-Calling Layer (Milestone 5).
Defines LLMProvider, message models, structured tool-call formats, and the explicit failure taxonomy.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from agent.models import FailureCategory


class LLMMessage(BaseModel):
    """
    Individual message in an LLM conversation thread.
    """
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class LLMToolCall(BaseModel):
    """
    Structured tool call emitted by an LLM model.
    """
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(description="Name of the tool to execute")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="JSON arguments for the tool")
    tool_call_id: Optional[str] = Field(default=None, description="Optional tool invocation ID")


class LLMResponse(BaseModel):
    """
    Standardized response emitted by an LLM provider.
    """
    model_config = ConfigDict(extra="forbid")

    content: Optional[str] = None
    tool_calls: List[LLMToolCall] = Field(default_factory=list)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    latency_ms: float = Field(default=0.0)
    model: str = Field(default="unknown")
    provider: str = Field(default="unknown")
    error: Optional[str] = None


class LLMProvider(ABC):
    """
    Abstract interface for LLM providers.
    Decouples RecoverAI from specific vendor SDKs and enables deterministic mock testing.
    """

    @abstractmethod
    def generate_tool_call(
        self,
        messages: List[LLMMessage],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0,
    ) -> LLMResponse:
        """
        Processes conversation messages and available tool definitions to produce a structured tool call.
        """
        pass
