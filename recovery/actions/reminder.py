"""
Provider-agnostic customer notification reminder action implementation.
"""

import hashlib
from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from recovery.models import ActionExecutionStatus, RecoveryCaseRecord, DecisionRecord
from recovery.actions.base import BaseActionProvider, ExecutionResult


class ReminderActionProvider(BaseActionProvider):
    """Sends a polite payment reminder push/SMS/email without a direct new invoice link."""

    @property
    def action(self) -> RecoveryAction:
        return RecoveryAction.REMINDER

    @property
    def cost_paise(self) -> int:
        return ACTION_COSTS_PAISE[RecoveryAction.REMINDER]

    def execute(
        self,
        case: RecoveryCaseRecord,
        decision: DecisionRecord,
        idempotency_key: str,
    ) -> ExecutionResult:
        ref_hash = hashlib.sha256(f"remind:{case.case_id}:{idempotency_key}".encode()).hexdigest()[:12]
        ref = f"rem_{ref_hash}"

        return ExecutionResult(
            status=ActionExecutionStatus.EXECUTED,
            provider_reference=ref,
            cost_paise=self.cost_paise,
            metadata={
                "channel": "push_notification_email",
                "template": "payment_reminder_v1",
                "customer_id": case.customer_id,
            },
        )
