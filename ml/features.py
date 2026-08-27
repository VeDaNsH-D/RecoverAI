"""
Feature extraction, transformations, and strict feature allowlist for RecoverAI ML models.
SECURITY GUARANTEE: Ingests ONLY observable PaymentCase features.
Zero hidden ground truth, latent states, or future outcomes can enter the feature matrix.
"""

import math
from typing import Dict, List, Set
import numpy as np

from simulator.config import FailureType, PaymentMethod
from simulator.schemas.case import PaymentCase


class DataLeakageError(ValueError):
    """Raised when an unauthorized, non-observable, or forbidden ground-truth field enters the ML pipeline."""
    pass


# ==============================================================================
# STRICT OBSERVABLE ALLOWLISTS
# ==============================================================================

OBSERVABLE_INPUT_FIELDS: Set[str] = {
    "case_id",
    "customer_id",
    "merchant_id",
    "amount_paise",
    "currency",
    "payment_method",
    "is_subscription",
    "customer_historical_success_rate",
    "customer_total_transactions",
    "customer_total_failures",
    "customer_avg_amount_paise",
    "customer_tenure_months",
    "failure_type",
    "retry_count",
    "hours_since_failure",
    "created_at",
}

FORBIDDEN_GROUND_TRUTH_PATTERNS: Set[str] = {
    "ground_truth",
    "latent",
    "optimal_action",
    "potential_outcomes",
    "actual_outcome",
    "is_recoverable",
    "latent_intent",
    "latent_funds",
    "oracle",
    "recovery_probabilities",
    "expected_net_values",
}

# The canonical, immutable list of engineered features produced for models
CANONICAL_FEATURE_NAMES: List[str] = [
    # Core numerical observables & deterministic transforms
    "amount_paise",
    "log_amount_inr",
    "customer_historical_success_rate",
    "historical_failure_rate",
    "customer_total_transactions",
    "log_total_transactions",
    "customer_total_failures",
    "customer_avg_amount_paise",
    "log_customer_avg_amount_inr",
    "amount_to_customer_avg_ratio",
    "customer_tenure_months",
    "log_tenure_months",
    "retry_count",
    "hours_since_failure",
    "log_hours_since_failure",
    "is_subscription",
    # One-hot encoded payment methods
    "payment_method_upi",
    "payment_method_card",
    "payment_method_netbanking",
    "payment_method_mandate",
    # One-hot encoded failure types
    "failure_type_temporary_failure",
    "failure_type_insufficient_funds",
    "failure_type_invalid_payment_method",
    "failure_type_unknown_failure",
]


class FeatureExtractor:
    """
    Extracts and standardizes observable features from PaymentCase instances.
    Enforces strict feature allowlisting and anti-leakage validation.
    """

    def __init__(self):
        self._feature_names = list(CANONICAL_FEATURE_NAMES)
        self._validate_feature_names_integrity()

    @property
    def feature_names(self) -> List[str]:
        """Returns the immutable ordered list of feature column names."""
        return list(self._feature_names)

    def _validate_feature_names_integrity(self) -> None:
        """Asserts that none of the canonical feature names contain forbidden ground-truth tokens."""
        for feat in self._feature_names:
            feat_lower = feat.lower()
            for forbidden in FORBIDDEN_GROUND_TRUTH_PATTERNS:
                if forbidden in feat_lower:
                    raise DataLeakageError(
                        f"CRITICAL SECURITY VIOLATION: Feature name '{feat}' contains forbidden token '{forbidden}'."
                    )

    def validate_case_integrity(self, case: PaymentCase) -> None:
        """
        Validates that a PaymentCase object contains only allowed observable fields.
        """
        case_dict = case.model_dump()
        for field_name in case_dict.keys():
            if field_name not in OBSERVABLE_INPUT_FIELDS:
                raise DataLeakageError(
                    f"CRITICAL SECURITY VIOLATION: Unauthorized field '{field_name}' found in input case."
                )
            field_lower = field_name.lower()
            for forbidden in FORBIDDEN_GROUND_TRUTH_PATTERNS:
                if forbidden in field_lower:
                    raise DataLeakageError(
                        f"CRITICAL SECURITY VIOLATION: Field '{field_name}' violates forbidden pattern '{forbidden}'."
                    )

    def extract_features_dict(self, case: PaymentCase) -> Dict[str, float]:
        """
        Extracts a dictionary of engineered numerical features from an observable PaymentCase.
        """
        self.validate_case_integrity(case)

        amt_paise = float(case.amount_paise)
        amt_inr = amt_paise / 100.0
        log_amt_inr = math.log(1.0 + max(0.0, amt_inr))

        cust_avg_paise = float(case.customer_avg_amount_paise)
        cust_avg_inr = cust_avg_paise / 100.0
        log_cust_avg_inr = math.log(1.0 + max(0.0, cust_avg_inr))

        ratio_amt = amt_paise / max(100.0, cust_avg_paise)

        succ_rate = float(case.customer_historical_success_rate)
        fail_rate = 1.0 - succ_rate

        tx_count = float(case.customer_total_transactions)
        log_tx_count = math.log(1.0 + max(0.0, tx_count))

        tenure = float(case.customer_tenure_months)
        log_tenure = math.log(1.0 + max(0.0, tenure))

        hours = float(case.hours_since_failure)
        log_hours = math.log(1.0 + max(0.0, hours))

        features: Dict[str, float] = {
            "amount_paise": amt_paise,
            "log_amount_inr": log_amt_inr,
            "customer_historical_success_rate": succ_rate,
            "historical_failure_rate": fail_rate,
            "customer_total_transactions": tx_count,
            "log_total_transactions": log_tx_count,
            "customer_total_failures": float(case.customer_total_failures),
            "customer_avg_amount_paise": cust_avg_paise,
            "log_customer_avg_amount_inr": log_cust_avg_inr,
            "amount_to_customer_avg_ratio": ratio_amt,
            "customer_tenure_months": tenure,
            "log_tenure_months": log_tenure,
            "retry_count": float(case.retry_count),
            "hours_since_failure": hours,
            "log_hours_since_failure": log_hours,
            "is_subscription": 1.0 if case.is_subscription else 0.0,
            # One-hot Payment Methods
            "payment_method_upi": 1.0 if case.payment_method == PaymentMethod.UPI else 0.0,
            "payment_method_card": 1.0 if case.payment_method == PaymentMethod.CARD else 0.0,
            "payment_method_netbanking": 1.0 if case.payment_method == PaymentMethod.NETBANKING else 0.0,
            "payment_method_mandate": 1.0 if case.payment_method == PaymentMethod.MANDATE else 0.0,
            # One-hot Failure Types
            "failure_type_temporary_failure": 1.0 if case.failure_type == FailureType.TEMPORARY_FAILURE else 0.0,
            "failure_type_insufficient_funds": 1.0 if case.failure_type == FailureType.INSUFFICIENT_FUNDS else 0.0,
            "failure_type_invalid_payment_method": 1.0 if case.failure_type == FailureType.INVALID_PAYMENT_METHOD else 0.0,
            "failure_type_unknown_failure": 1.0 if case.failure_type == FailureType.UNKNOWN_FAILURE else 0.0,
        }

        return features

    def extract_features_array(self, case: PaymentCase) -> np.ndarray:
        """
        Extracts a 1D numpy array of features in canonical order.
        """
        feat_dict = self.extract_features_dict(case)
        return np.array([feat_dict[name] for name in self._feature_names], dtype=np.float64)

    def transform_cases(self, cases: List[PaymentCase]) -> np.ndarray:
        """
        Transforms a batch of PaymentCase objects into a 2D numpy feature matrix (N x D).
        """
        if not cases:
            return np.empty((0, len(self._feature_names)), dtype=np.float64)

        matrix = np.zeros((len(cases), len(self._feature_names)), dtype=np.float64)
        for i, case in enumerate(cases):
            matrix[i] = self.extract_features_array(case)
        return matrix
