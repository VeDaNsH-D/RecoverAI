"""
Abstract base class for all RecoverAI recovery policies.
Policies receive ONLY observable features (PaymentCase) and NEVER ground truth.
"""

from abc import ABC, abstractmethod
from simulator.config import RecoveryAction
from simulator.schemas.case import PaymentCase


class BasePolicy(ABC):
    """
    Abstract recovery policy interface.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Returns the unique policy name."""
        pass

    @abstractmethod
    def predict(self, case: PaymentCase) -> RecoveryAction:
        """
        Decides which recovery action to take for a given observable payment case.

        Parameters:
            case: Observable PaymentCase features.

        Returns:
            Selected RecoveryAction.
        """
        pass
