"""
Provider-agnostic payment link generation and dispatch action implementation.
"""

import hashlib
from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from recovery.models import ActionExecutionStatus, RecoveryCaseRecord, DecisionRecord
from recovery.actions.base import BaseActionProvider, ExecutionResult


class PaymentLinkActionProvider(BaseActionProvider):
    """Generates and dispatches an asynchronous payment link via SMS/WhatsApp."""

    @property
    def action(self) -> RecoveryAction:
        return RecoveryAction.PAYMENT_LINK

    @property
    def cost_paise(self) -> int:
        return ACTION_COSTS_PAISE[RecoveryAction.PAYMENT_LINK]

    def execute(
        self,
        case: RecoveryCaseRecord,
        decision: DecisionRecord,
        idempotency_key: str,
    ) -> ExecutionResult:
        ref_hash = hashlib.sha256(f"plink:{case.case_id}:{idempotency_key}".encode()).hexdigest()[:12]
        ref = f"plink_{ref_hash}"

        return ExecutionResult(
            status=ActionExecutionStatus.EXECUTED,
            provider_reference=ref,
            cost_paise=self.cost_paise,
            metadata={
                "channel": "sms_whatsapp",
                "payment_url": f"https://rzp.io/i/{ref}",
                "amount_paise": case.amount_paise,
                "expires_in_hours": 24,
            },
        )
