"""
Base tool interface for RecoverAI Agent Orchestration.
All tools enforce strict schemas, authorization boundaries, and deterministic execution.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict
from agent.models import AgentContext


class BaseTool(ABC):
    """
    Abstract base class for all Recovery Agent tools.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique machine-readable tool name."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human/LLM-readable description of what this tool does."""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> Dict[str, Any]:
        """JSON Schema specification of allowed tool inputs."""
        pass

    @abstractmethod
    def execute(self, context: AgentContext, **kwargs: Any) -> Dict[str, Any]:
        """
        Executes the tool logic, updating agent context and returning a safe output dictionary.
        """
        pass
