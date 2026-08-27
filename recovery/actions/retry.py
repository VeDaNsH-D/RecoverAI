"""
Provider-agnostic automated gateway retry action implementation.
"""

import hashlib
from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from recovery.models import ActionExecutionStatus, RecoveryCaseRecord, DecisionRecord
from recovery.actions.base import BaseActionProvider, ExecutionResult


class RetryActionProvider(BaseActionProvider):
    """Executes automated technical retry against payment gateway/network."""

    @property
    def action(self) -> RecoveryAction:
        return RecoveryAction.RETRY

    @property
    def cost_paise(self) -> int:
        return ACTION_COSTS_PAISE[RecoveryAction.RETRY]

    def execute(
        self,
        case: RecoveryCaseRecord,
        decision: DecisionRecord,
        idempotency_key: str,
    ) -> ExecutionResult:
        # Deterministic reference based on case and idempotency key
        ref_hash = hashlib.sha256(f"retry:{case.case_id}:{idempotency_key}".encode()).hexdigest()[:12]
        ref = f"gw_retry_{ref_hash}"

        return ExecutionResult(
            status=ActionExecutionStatus.EXECUTED,
            provider_reference=ref,
            cost_paise=self.cost_paise,
            metadata={
                "gateway": "mock_razorpay_gateway",
                "attempt_type": "automated_server_retry",
                "amount_paise": case.amount_paise,
            },
        )
