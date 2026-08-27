"""
Deterministic Rule-Based Baseline Policy for RecoverAI.
Represents common industry heuristic logic.
"""

from simulator.config import FailureType, RecoveryAction
from simulator.schemas.case import PaymentCase
from simulator.policies.base import BasePolicy


class RuleBasedBaselinePolicy(BasePolicy):
    """
    Standard heuristic baseline policy:
    - temporary_failure & retry_count < 3 -> retry
    - insufficient_funds -> payment_link
    - invalid_payment_method -> payment_link
    - unknown_failure or retry_count >= 3 -> escalate
    """

    @property
    def name(self) -> str:
        return "rule_baseline"

    def predict(self, case: PaymentCase) -> RecoveryAction:
        """
        Determines recovery action based on deterministic rules.
        """
        # Safety bound: If already retried 3 or more times, escalate rather than looping retries
        if case.retry_count >= 3:
            return RecoveryAction.ESCALATE

        if case.failure_type == FailureType.TEMPORARY_FAILURE:
            return RecoveryAction.RETRY
        elif case.failure_type == FailureType.INSUFFICIENT_FUNDS:
            return RecoveryAction.PAYMENT_LINK
        elif case.failure_type == FailureType.INVALID_PAYMENT_METHOD:
            return RecoveryAction.PAYMENT_LINK
        elif case.failure_type == FailureType.UNKNOWN_FAILURE:
            return RecoveryAction.ESCALATE
        else:
            return RecoveryAction.ESCALATE
