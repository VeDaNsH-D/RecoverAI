"""
Tests for recovery policy behaviors (NoAction, RuleBaseline, Oracle).
"""

import pytest
from simulator.config import FailureType, PaymentMethod, RecoveryAction
from simulator.generators.customer_generator import generate_customers
from simulator.generators.case_generator import generate_cases
from simulator.generators.ground_truth_generator import generate_ground_truth
from simulator.schemas.case import PaymentCase
from simulator.policies.no_action import NoActionPolicy
from simulator.policies.rule_baseline import RuleBasedBaselinePolicy
from simulator.policies.oracle import OraclePolicy


def make_dummy_case(
    failure_type: FailureType,
    retry_count: int = 0,
    amount_paise: int = 150000,
) -> PaymentCase:
    return PaymentCase(
        case_id="case_test_001",
        customer_id="cust_000001",
        merchant_id="merch_test",
        amount_paise=amount_paise,
        currency="INR",
        payment_method=PaymentMethod.UPI,
        is_subscription=False,
        customer_historical_success_rate=0.85,
        customer_total_transactions=20,
        customer_total_failures=3,
        customer_avg_amount_paise=150000,
        customer_tenure_months=12,
        failure_type=failure_type,
        retry_count=retry_count,
        hours_since_failure=2.0,
        created_at="2026-08-27T08:00:00Z",
    )


def test_no_action_policy():
    policy = NoActionPolicy()
    assert policy.name == "no_action"
    for ft in FailureType:
        case = make_dummy_case(ft, retry_count=0)
        assert policy.predict(case) == RecoveryAction.NO_ACTION


def test_rule_baseline_policy():
    policy = RuleBasedBaselinePolicy()
    assert policy.name == "rule_baseline"

    # Temporary failure < 3 retries -> RETRY
    case_temp = make_dummy_case(FailureType.TEMPORARY_FAILURE, retry_count=0)
    assert policy.predict(case_temp) == RecoveryAction.RETRY

    case_temp_retry2 = make_dummy_case(FailureType.TEMPORARY_FAILURE, retry_count=2)
    assert policy.predict(case_temp_retry2) == RecoveryAction.RETRY

    # Insufficient funds -> PAYMENT_LINK
    case_funds = make_dummy_case(FailureType.INSUFFICIENT_FUNDS, retry_count=0)
    assert policy.predict(case_funds) == RecoveryAction.PAYMENT_LINK

    # Invalid payment method -> PAYMENT_LINK
    case_invalid = make_dummy_case(FailureType.INVALID_PAYMENT_METHOD, retry_count=0)
    assert policy.predict(case_invalid) == RecoveryAction.PAYMENT_LINK

    # Unknown failure -> ESCALATE
    case_unknown = make_dummy_case(FailureType.UNKNOWN_FAILURE, retry_count=0)
    assert policy.predict(case_unknown) == RecoveryAction.ESCALATE

    # Retry count >= 3 -> ESCALATE regardless of failure type
    case_max_retries = make_dummy_case(FailureType.TEMPORARY_FAILURE, retry_count=3)
    assert policy.predict(case_max_retries) == RecoveryAction.ESCALATE


def test_oracle_policy_matches_ground_truth():
    customers = generate_customers(count=20, seed=42)
    cases = generate_cases(customers=customers, total_cases=50, seed=42)
    cust_map = {c.customer_id: c for c in customers}
    gt_map = generate_ground_truth(cases, cust_map, seed=42)

    oracle = OraclePolicy(ground_truth_map=gt_map)
    assert oracle.name == "oracle"

    for case in cases:
        chosen_action = oracle.predict(case)
        assert chosen_action == gt_map[case.case_id].optimal_action
