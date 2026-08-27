"""
No-Action Baseline Policy for RecoverAI.
Takes no intervention on any case, serving as the natural recovery lower bound.
"""

from simulator.config import RecoveryAction
from simulator.schemas.case import PaymentCase
from simulator.policies.base import BasePolicy


class NoActionPolicy(BasePolicy):
    """
    Policy that takes NO_ACTION for all payment failure cases.
    """

    @property
    def name(self) -> str:
        return "no_action"

    def predict(self, case: PaymentCase) -> RecoveryAction:
        """Always returns NO_ACTION."""
        return RecoveryAction.NO_ACTION
