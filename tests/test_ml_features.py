"""
Tests for ML feature extraction, transformations, and strict anti-leakage allowlists.
"""

import pytest
import numpy as np
from pydantic import BaseModel

from simulator.config import FailureType, PaymentMethod
from simulator.schemas.case import PaymentCase
from ml.features import (
    FeatureExtractor,
    DataLeakageError,
    CANONICAL_FEATURE_NAMES,
    FORBIDDEN_GROUND_TRUTH_PATTERNS,
)


def make_test_case(
    amount_paise: int = 150000,
    payment_method: PaymentMethod = PaymentMethod.UPI,
    failure_type: FailureType = FailureType.TEMPORARY_FAILURE,
    retry_count: int = 0,
    hours_since_failure: float = 2.5,
    customer_historical_success_rate: float = 0.85,
    customer_total_transactions: int = 20,
    customer_total_failures: int = 3,
    customer_avg_amount_paise: int = 120000,
    customer_tenure_months: int = 12,
    is_subscription: bool = False,
) -> PaymentCase:
    return PaymentCase(
        case_id="case_test_001",
        customer_id="cust_test_001",
        merchant_id="merch_test",
        amount_paise=amount_paise,
        currency="INR",
        payment_method=payment_method,
        is_subscription=is_subscription,
        customer_historical_success_rate=customer_historical_success_rate,
        customer_total_transactions=customer_total_transactions,
        customer_total_failures=customer_total_failures,
        customer_avg_amount_paise=customer_avg_amount_paise,
        customer_tenure_months=customer_tenure_months,
        failure_type=failure_type,
        retry_count=retry_count,
        hours_since_failure=hours_since_failure,
        created_at="2026-08-27T08:00:00Z",
    )


def test_feature_extractor_initialization_and_names():
    extractor = FeatureExtractor()
    assert extractor.feature_names == CANONICAL_FEATURE_NAMES
    assert len(extractor.feature_names) == 24

    # Ensure no forbidden keywords exist in feature names
    for name in extractor.feature_names:
        for forbidden in FORBIDDEN_GROUND_TRUTH_PATTERNS:
            assert forbidden not in name.lower()


def test_feature_extraction_values_and_transformations():
    extractor = FeatureExtractor()
    case = make_test_case(
        amount_paise=250000,  # ₹2,500
        payment_method=PaymentMethod.CARD,
        failure_type=FailureType.INSUFFICIENT_FUNDS,
        retry_count=1,
        hours_since_failure=5.0,
        customer_historical_success_rate=0.80,
        customer_total_transactions=50,
        customer_total_failures=10,
        customer_avg_amount_paise=200000,  # ₹2,000
        customer_tenure_months=24,
        is_subscription=True,
    )

    feat_dict = extractor.extract_features_dict(case)
    assert len(feat_dict) == len(CANONICAL_FEATURE_NAMES)

    # Check numerical transforms
    assert feat_dict["amount_paise"] == 250000.0
    assert abs(feat_dict["log_amount_inr"] - np.log(1.0 + 2500.0)) < 1e-5
    assert feat_dict["customer_historical_success_rate"] == 0.80
    assert abs(feat_dict["historical_failure_rate"] - 0.20) < 1e-5
    assert feat_dict["amount_to_customer_avg_ratio"] == 250000.0 / 200000.0
    assert feat_dict["is_subscription"] == 1.0
    assert feat_dict["retry_count"] == 1.0

    # One-hot checks: CARD should be 1.0, others 0.0
    assert feat_dict["payment_method_card"] == 1.0
    assert feat_dict["payment_method_upi"] == 0.0
    assert feat_dict["payment_method_netbanking"] == 0.0
    assert feat_dict["payment_method_mandate"] == 0.0

    # One-hot checks: INSUFFICIENT_FUNDS should be 1.0, others 0.0
    assert feat_dict["failure_type_insufficient_funds"] == 1.0
    assert feat_dict["failure_type_temporary_failure"] == 0.0
    assert feat_dict["failure_type_invalid_payment_method"] == 0.0
    assert feat_dict["failure_type_unknown_failure"] == 0.0


def test_feature_determinism():
    extractor = FeatureExtractor()
    case = make_test_case()

    vec1 = extractor.extract_features_array(case)
    vec2 = extractor.extract_features_array(case)

    np.testing.assert_array_equal(vec1, vec2)
    assert vec1.shape == (24,)


def test_batch_feature_transformation():
    extractor = FeatureExtractor()
    cases = [
        make_test_case(amount_paise=100000, payment_method=PaymentMethod.UPI),
        make_test_case(amount_paise=200000, payment_method=PaymentMethod.CARD),
        make_test_case(amount_paise=300000, payment_method=PaymentMethod.NETBANKING),
    ]

    matrix = extractor.transform_cases(cases)
    assert matrix.shape == (3, 24)
    assert matrix.dtype == np.float64
    assert matrix[0, 0] == 100000.0
    assert matrix[1, 0] == 200000.0
    assert matrix[2, 0] == 300000.0


def test_anti_leakage_rejection_of_forbidden_fields():
    extractor = FeatureExtractor()

    # Create a mock corrupted case with ground-truth fields injected
    class CorruptedCase(BaseModel):
        case_id: str = "case_bad"
        customer_id: str = "cust_bad"
        merchant_id: str = "merch_bad"
        amount_paise: int = 100000
        currency: str = "INR"
        payment_method: PaymentMethod = PaymentMethod.UPI
        is_subscription: bool = False
        customer_historical_success_rate: float = 0.9
        customer_total_transactions: int = 10
        customer_total_failures: int = 1
        customer_avg_amount_paise: int = 100000
        customer_tenure_months: int = 10
        failure_type: FailureType = FailureType.TEMPORARY_FAILURE
        retry_count: int = 0
        hours_since_failure: float = 1.0
        created_at: str = "2026-08-27T08:00:00Z"
        # Injected forbidden fields:
        optimal_action: str = "retry"
        ground_truth_prob: float = 0.95

    corrupted = CorruptedCase()

    # Attempting to validate or extract features must raise DataLeakageError
    with pytest.raises(DataLeakageError, match="CRITICAL SECURITY VIOLATION"):
        extractor.validate_case_integrity(corrupted)


def test_edge_cases():
    extractor = FeatureExtractor()

    # Zero amount & zero tenure
    case_zero = make_test_case(amount_paise=0, customer_avg_amount_paise=0, customer_tenure_months=0)
    arr_zero = extractor.extract_features_array(case_zero)
    assert not np.isnan(arr_zero).any()
    assert not np.isinf(arr_zero).any()

    # Extreme high amount (₹50,00,000 = 500,000,000 paise)
    case_high = make_test_case(amount_paise=500_000_000, retry_count=10)
    arr_high = extractor.extract_features_array(case_high)
    assert not np.isnan(arr_high).any()
    assert not np.isinf(arr_high).any()
