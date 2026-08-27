"""
Tests for edge cases: zero amounts, very high amounts, extreme retries, and boundary inputs.
"""

import pytest
from simulator.config import FailureType, PaymentMethod, RecoveryAction
from simulator.schemas.customer import CustomerProfile
from simulator.schemas.case import PaymentCase
from simulator.generators.ground_truth_generator import generate_ground_truth
from simulator.outcome_simulator import OutcomeSimulator
from simulator.evaluator import EvaluationEngine
from simulator.policies.rule_baseline import RuleBasedBaselinePolicy


def test_zero_amount_case():
    cust = CustomerProfile(
        customer_id="cust_zero",
        historical_success_rate=0.90,
        total_transactions=10,
        total_failures=1,
        avg_transaction_amount_paise=0,
        default_payment_method=PaymentMethod.UPI,
        is_subscription=False,
        tenure_months=6,
    )
    case = PaymentCase(
        case_id="case_zero",
        customer_id="cust_zero",
        merchant_id="merch_test",
        amount_paise=0,
        currency="INR",
        payment_method=PaymentMethod.UPI,
        is_subscription=False,
        customer_historical_success_rate=0.90,
        customer_total_transactions=10,
        customer_total_failures=1,
        customer_avg_amount_paise=0,
        customer_tenure_months=6,
        failure_type=FailureType.TEMPORARY_FAILURE,
        retry_count=0,
        hours_since_failure=1.0,
        created_at="2026-08-27T08:00:00Z",
    )

    cust_map = {cust.customer_id: cust}
    gt_map = generate_ground_truth([case], cust_map, seed=42)
    assert len(gt_map) == 1
    gt = gt_map["case_zero"]

    sim = OutcomeSimulator(ground_truth_map=gt_map)
    res = sim.execute_action(case, RecoveryAction.RETRY)

    # If recovered, gross recovered is 0 paise
    if res.recovered:
        assert res.recovered_amount_paise == 0
        assert res.net_recovered_amount_paise == -res.intervention_cost_paise


def test_extreme_high_amount_case():
    """Verify that extreme transaction amount (₹10,00,000) does not cause overflow or errors."""
    amount_paise = 100_000_000  # ₹10,00,000
    cust = CustomerProfile(
        customer_id="cust_whale",
        historical_success_rate=0.95,
        total_transactions=100,
        total_failures=5,
        avg_transaction_amount_paise=amount_paise,
        default_payment_method=PaymentMethod.NETBANKING,
        is_subscription=False,
        tenure_months=36,
    )
    case = PaymentCase(
        case_id="case_whale",
        customer_id="cust_whale",
        merchant_id="merch_test",
        amount_paise=amount_paise,
        currency="INR",
        payment_method=PaymentMethod.NETBANKING,
        is_subscription=False,
        customer_historical_success_rate=0.95,
        customer_total_transactions=100,
        customer_total_failures=5,
        customer_avg_amount_paise=amount_paise,
        customer_tenure_months=36,
        failure_type=FailureType.UNKNOWN_FAILURE,
        retry_count=1,
        hours_since_failure=0.5,
        created_at="2026-08-27T08:00:00Z",
    )

    cust_map = {cust.customer_id: cust}
    gt_map = generate_ground_truth([case], cust_map, seed=42)
    gt = gt_map["case_whale"]

    # For high amount unknown failure, escalate should have high expected net value
    assert gt.optimal_action in RecoveryAction
    assert gt.expected_net_values_paise[RecoveryAction.ESCALATE] > 0


def test_repeated_failures_safety_boundary():
    """Verify that high retry counts trigger escalation safety rule."""
    case = PaymentCase(
        case_id="case_fatigued",
        customer_id="cust_001",
        merchant_id="merch_test",
        amount_paise=500000,
        currency="INR",
        payment_method=PaymentMethod.CARD,
        is_subscription=True,
        customer_historical_success_rate=0.70,
        customer_total_transactions=15,
        customer_total_failures=5,
        customer_avg_amount_paise=500000,
        customer_tenure_months=10,
        failure_type=FailureType.TEMPORARY_FAILURE,
        retry_count=5,  # Max retries exceeded
        hours_since_failure=48.0,
        created_at="2026-08-27T08:00:00Z",
    )
    policy = RuleBasedBaselinePolicy()
    assert policy.predict(case) == RecoveryAction.ESCALATE
