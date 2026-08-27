"""
Provider-agnostic passive observation (no action) implementation.
"""

import hashlib
from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from recovery.models import ActionExecutionStatus, RecoveryCaseRecord, DecisionRecord
from recovery.actions.base import BaseActionProvider, ExecutionResult


class NoActionProvider(BaseActionProvider):
    """Executes passive observation without initiating external communication or gateway retries."""

    @property
    def action(self) -> RecoveryAction:
        return RecoveryAction.NO_ACTION

    @property
    def cost_paise(self) -> int:
        return ACTION_COSTS_PAISE[RecoveryAction.NO_ACTION]

    def execute(
        self,
        case: RecoveryCaseRecord,
        decision: DecisionRecord,
        idempotency_key: str,
    ) -> ExecutionResult:
        ref_hash = hashlib.sha256(f"no_act:{case.case_id}:{idempotency_key}".encode()).hexdigest()[:12]
        ref = f"passive_obs_{ref_hash}"

        return ExecutionResult(
            status=ActionExecutionStatus.EXECUTED,
            provider_reference=ref,
            cost_paise=self.cost_paise,
            metadata={
                "strategy": "passive_observation",
                "cost_paise": 0,
                "reason": "negative_or_suboptimal_intervention_ev",
            },
        )
