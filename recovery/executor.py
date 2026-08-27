"""
Action Executor and Provider Registry for RecoverAI.
Dispatches selected recovery actions to the appropriate action provider implementation.
GUARANTEE: The executor NEVER chooses an action; it strictly executes the action chosen by the Decision Engine.
"""

from typing import Dict
from simulator.config import RecoveryAction
from recovery.models import ActionExecutionStatus, RecoveryCaseRecord, DecisionRecord
from recovery.actions.base import BaseActionProvider, ExecutionResult
from recovery.actions.retry import RetryActionProvider
from recovery.actions.payment_link import PaymentLinkActionProvider
from recovery.actions.reminder import ReminderActionProvider
from recovery.actions.escalate import EscalateActionProvider
from recovery.actions.no_action import NoActionProvider


class ActionExecutor:
    """
    Provider-agnostic execution dispatcher for RecoverAI actions.
    """

    def __init__(self):
        self._providers: Dict[RecoveryAction, BaseActionProvider] = {
            RecoveryAction.NO_ACTION: NoActionProvider(),
            RecoveryAction.RETRY: RetryActionProvider(),
            RecoveryAction.PAYMENT_LINK: PaymentLinkActionProvider(),
            RecoveryAction.REMINDER: ReminderActionProvider(),
            RecoveryAction.ESCALATE: EscalateActionProvider(),
        }

    def register_provider(self, action: RecoveryAction, provider: BaseActionProvider) -> None:
        """Allows registering or overriding a provider implementation (e.g. for testing)."""
        self._providers[action] = provider

    def execute_action(
        self,
        case: RecoveryCaseRecord,
        decision: DecisionRecord,
        action: RecoveryAction,
        idempotency_key: str,
        force_failure: bool = False,
    ) -> ExecutionResult:
        """
        Dispatches the action to the registered provider.
        """
        if force_failure:
            return ExecutionResult(
                status=ActionExecutionStatus.FAILED,
                provider_reference="",
                cost_paise=0,
                error_message="Mock provider connection timeout / gateway unreachable.",
                metadata={"forced_failure": True},
            )

        provider = self._providers.get(action)
        if provider is None:
            return ExecutionResult(
                status=ActionExecutionStatus.FAILED,
                provider_reference="",
                cost_paise=0,
                error_message=f"No provider registered for action '{action.value}'.",
            )

        return provider.execute(
            case=case,
            decision=decision,
            idempotency_key=idempotency_key,
        )
