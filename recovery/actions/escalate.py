"""
Provider-agnostic manual operations escalation action implementation.
"""

import hashlib
from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from recovery.models import ActionExecutionStatus, RecoveryCaseRecord, DecisionRecord
from recovery.actions.base import BaseActionProvider, ExecutionResult


class EscalateActionProvider(BaseActionProvider):
    """Creates a high-priority support operations ticket for human customer outreach."""

    @property
    def action(self) -> RecoveryAction:
        return RecoveryAction.ESCALATE

    @property
    def cost_paise(self) -> int:
        return ACTION_COSTS_PAISE[RecoveryAction.ESCALATE]

    def execute(
        self,
        case: RecoveryCaseRecord,
        decision: DecisionRecord,
        idempotency_key: str,
    ) -> ExecutionResult:
        ref_hash = hashlib.sha256(f"escalate:{case.case_id}:{idempotency_key}".encode()).hexdigest()[:12]
        ref = f"ops_ticket_{ref_hash}"

        return ExecutionResult(
            status=ActionExecutionStatus.EXECUTED,
            provider_reference=ref,
            cost_paise=self.cost_paise,
            metadata={
                "system": "support_ops_zendesk_mock",
                "priority": "HIGH",
                "amount_paise": case.amount_paise,
                "assigned_queue": "enterprise_revenue_recovery",
            },
        )
