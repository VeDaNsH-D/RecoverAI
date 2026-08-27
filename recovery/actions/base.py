"""
Abstract base class and execution results for RecoverAI action providers.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict

from simulator.config import RecoveryAction
from recovery.models import ActionExecutionStatus, RecoveryCaseRecord, DecisionRecord


class ExecutionResult(BaseModel):
    """Result of an action provider execution attempt."""
    model_config = ConfigDict(frozen=True)

    status: ActionExecutionStatus
    provider_reference: str
    cost_paise: int
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = {}


class BaseActionProvider(ABC):
    """
    Abstract interface for provider-agnostic recovery action execution.
    The action provider executes ONLY the action chosen by RecoverAI's decision engine.
    """

    @property
    @abstractmethod
    def action(self) -> RecoveryAction:
        """The specific recovery action this provider handles."""
        pass

    @property
    @abstractmethod
    def cost_paise(self) -> int:
        """Standard operational cost in integer paise."""
        pass

    @abstractmethod
    def execute(
        self,
        case: RecoveryCaseRecord,
        decision: DecisionRecord,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Dispatches the action to the underlying provider or mock.
        Must be deterministic and idempotent.
        """
        pass
