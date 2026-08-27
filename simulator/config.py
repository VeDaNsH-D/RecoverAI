"""
Simulation configuration, parameters, and synthetic assumptions for RecoverAI.
All internal monetary values are in integer paise (1 INR = 100 paise).
"""

from enum import Enum
from typing import Dict


class FailureType(str, Enum):
    """Payment failure taxonomy."""
    TEMPORARY_FAILURE = "temporary_failure"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    INVALID_PAYMENT_METHOD = "invalid_payment_method"
    UNKNOWN_FAILURE = "unknown_failure"


class RecoveryAction(str, Enum):
    """Bounded recovery action space."""
    NO_ACTION = "no_action"
    RETRY = "retry"
    PAYMENT_LINK = "payment_link"
    REMINDER = "reminder"
    ESCALATE = "escalate"


class PaymentMethod(str, Enum):
    """Supported payment methods."""
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"
    MANDATE = "mandate"


# ==============================================================================
# SYNTHETIC SIMULATION ASSUMPTIONS (Friction Costs & Latencies)
# These represent synthetic benchmark operational costs for computing net payoff.
# They are simulation assumptions and DO NOT represent actual Razorpay pricing.
# ==============================================================================

ACTION_COSTS_PAISE: Dict[RecoveryAction, int] = {
    RecoveryAction.NO_ACTION: 0,        # ₹0.00
    RecoveryAction.RETRY: 200,          # ₹2.00 (API / gateway retry fee)
    RecoveryAction.PAYMENT_LINK: 1000,  # ₹10.00 (SMS/WhatsApp link + user friction)
    RecoveryAction.REMINDER: 500,       # ₹5.00 (Notification / reminder friction)
    RecoveryAction.ESCALATE: 5000,      # ₹50.00 (Human agent / manual ops overhead)
}

ACTION_NOMINAL_LATENCY_HOURS: Dict[RecoveryAction, float] = {
    RecoveryAction.NO_ACTION: 0.0,
    RecoveryAction.RETRY: 0.5,
    RecoveryAction.PAYMENT_LINK: 4.0,
    RecoveryAction.REMINDER: 12.0,
    RecoveryAction.ESCALATE: 24.0,
}

# Failure Type Base Probabilities
FAILURE_TYPE_WEIGHTS: Dict[FailureType, float] = {
    FailureType.TEMPORARY_FAILURE: 0.40,
    FailureType.INSUFFICIENT_FUNDS: 0.30,
    FailureType.INVALID_PAYMENT_METHOD: 0.20,
    FailureType.UNKNOWN_FAILURE: 0.10,
}

# Payment Method Distribution
PAYMENT_METHOD_WEIGHTS: Dict[PaymentMethod, float] = {
    PaymentMethod.UPI: 0.50,
    PaymentMethod.CARD: 0.30,
    PaymentMethod.NETBANKING: 0.15,
    PaymentMethod.MANDATE: 0.05,
}

# Default Split Ratios
DEFAULT_TRAIN_RATIO = 0.70
DEFAULT_VAL_RATIO = 0.15
DEFAULT_TEST_RATIO = 0.15

# Default Simulation Scale
DEFAULT_CUSTOMER_COUNT = 2000
DEFAULT_CASE_COUNT = 10000
DEFAULT_RANDOM_SEED = 42
