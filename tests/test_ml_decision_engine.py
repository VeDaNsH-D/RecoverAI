"""
Tests for RecoveryDecisionEngine: Expected Net Value calculations, safety constraints, and auditability.
"""

import pytest
import math

from simulator.config import RecoveryAction, ACTION_COSTS_PAISE, FailureType, PaymentMethod
from simulator.schemas.case import PaymentCase
from ml.decision_engine import (
    ActionValue,
    DecisionResult,
    RecoveryDecisionEngine,
    MAX_RETRY_COUNT_ALLOWED,
    MIN_AMOUNT_PAISE_FOR_ESCALATE,
)


def make_case(
    amount_paise: int = 100000,  # ₹1,000
    retry_count: int = 0,
    failure_type: FailureType = FailureType.TEMPORARY_FAILURE,
    payment_method: PaymentMethod = PaymentMethod.UPI,
    hours_since_failure: float = 1.0,
) -> PaymentCase:
    return PaymentCase(
        case_id="case_dec_001",
        customer_id="cust_dec_001",
        merchant_id="merch_prod",
        amount_paise=amount_paise,
        currency="INR",
        payment_method=payment_method,
        is_subscription=False,
        customer_historical_success_rate=0.85,
        customer_total_transactions=20,
        customer_total_failures=2,
        customer_avg_amount_paise=100000,
        customer_tenure_months=12,
        failure_type=failure_type,
        retry_count=retry_count,
        hours_since_failure=hours_since_failure,
        created_at="2026-08-27T08:00:00Z",
    )


def test_costs_match_simulator_configuration():
    engine = RecoveryDecisionEngine()
    case = make_case()
    custom_probs = {act: 0.5 for act in RecoveryAction}
    res = engine.evaluate_case(case, custom_probabilities=custom_probs)

    for act in RecoveryAction:
        assert res.action_values[act].action_cost_paise == ACTION_COSTS_PAISE[act]


def test_synthetic_expected_net_value_optimization():
    """
    CRITICAL SYNTHETIC TEST:
    Amount = ₹10,000 (1,000,000 paise)
    no_action: P = 0.02 -> Gross = 20,000, Cost = 0, Net = 20,000
    retry: P = 0.20 -> Gross = 200,000, Cost = 200, Net = 199,800
    payment_link: P = 0.70 -> Gross = 700,000, Cost = 1,000, Net = 699,000
    reminder: P = 0.40 -> Gross = 400,000, Cost = 500, Net = 399,500
    escalate: P = 0.80 -> Gross = 800,000, Cost = 5,000, Net = 795,000
    Optimal action: ESCALATE (Net = 795,000 paise = ₹7,950.00).
    """
    engine = RecoveryDecisionEngine()
    case = make_case(amount_paise=1_000_000, retry_count=0)

    custom_probs = {
        RecoveryAction.NO_ACTION: 0.02,
        RecoveryAction.RETRY: 0.20,
        RecoveryAction.PAYMENT_LINK: 0.70,
        RecoveryAction.REMINDER: 0.40,
        RecoveryAction.ESCALATE: 0.80,
    }

    res = engine.evaluate_case(case, custom_probabilities=custom_probs)
    assert res.selected_action == RecoveryAction.ESCALATE
    assert res.selected_expected_net_paise == 795_000
    # Margin over payment_link (795,000 - 699,000 = 96,000 paise)
    assert res.decision_margin_paise == 96_000
    assert res.action_values[RecoveryAction.ESCALATE].allowed is True


def test_safety_no_action_always_available():
    engine = RecoveryDecisionEngine()
    case = make_case(amount_paise=5000, retry_count=5)  # micro-ticket with high retries
    custom_probs = {act: 0.0 for act in RecoveryAction}

    res = engine.evaluate_case(case, custom_probabilities=custom_probs)
    assert res.action_values[RecoveryAction.NO_ACTION].allowed is True
    assert res.selected_action == RecoveryAction.NO_ACTION


def test_safety_retry_count_suppression_boundary():
    engine = RecoveryDecisionEngine()

    custom_probs = {
        RecoveryAction.NO_ACTION: 0.0,
        RecoveryAction.RETRY: 0.95,       # High probability
        RecoveryAction.PAYMENT_LINK: 0.50,
        RecoveryAction.REMINDER: 0.30,
        RecoveryAction.ESCALATE: 0.60,
    }

    # retry_count = 1: RETRY MUST BE ALLOWED
    case_retried_1 = make_case(amount_paise=100000, retry_count=1)
    res_1 = engine.evaluate_case(case_retried_1, custom_probabilities=custom_probs)
    assert res_1.action_values[RecoveryAction.RETRY].allowed is True
    assert res_1.selected_action == RecoveryAction.RETRY

    # retry_count = 2: RETRY MUST BE DISQUALIFIED
    case_retried_2 = make_case(amount_paise=100000, retry_count=2)
    res_2 = engine.evaluate_case(case_retried_2, custom_probabilities=custom_probs)
    assert res_2.action_values[RecoveryAction.RETRY].allowed is False
    assert "max_retries_exceeded" in res_2.action_values[RecoveryAction.RETRY].disqualification_reason
    # With retry disqualified, escalate (0.60 * 100k - 5k = 55k) or link (0.50 * 100k - 1k = 49k) should win
    assert res_2.selected_action == RecoveryAction.ESCALATE

    # retry_count = 3: RETRY MUST BE DISQUALIFIED
    case_retried_3 = make_case(amount_paise=100000, retry_count=3)
    res_3 = engine.evaluate_case(case_retried_3, custom_probabilities=custom_probs)
    assert res_3.action_values[RecoveryAction.RETRY].allowed is False


def test_safety_micro_ticket_escalation_suppression_boundary():
    engine = RecoveryDecisionEngine()

    custom_probs = {
        RecoveryAction.NO_ACTION: 0.0,
        RecoveryAction.RETRY: 0.10,
        RecoveryAction.PAYMENT_LINK: 0.20,
        RecoveryAction.REMINDER: 0.10,
        RecoveryAction.ESCALATE: 0.90,  # High probability
    }

    # Amount = ₹199 (19,900 paise < 20,000 paise): ESCALATE MUST BE DISQUALIFIED
    case_micro = make_case(amount_paise=19_900)
    res_micro = engine.evaluate_case(case_micro, custom_probabilities=custom_probs)
    assert res_micro.action_values[RecoveryAction.ESCALATE].allowed is False
    assert "micro_ticket_protection" in res_micro.action_values[RecoveryAction.ESCALATE].disqualification_reason
    # Fallback to payment_link
    assert res_micro.selected_action == RecoveryAction.PAYMENT_LINK

    # Amount = ₹200 (20,000 paise == 20,000 paise): ESCALATE MUST BE ALLOWED
    case_boundary = make_case(amount_paise=20_000)
    res_boundary = engine.evaluate_case(case_boundary, custom_probabilities=custom_probs)
    assert res_boundary.action_values[RecoveryAction.ESCALATE].allowed is True
    # 0.90 * 20,000 = 18,000 - 5,000 = 13,000 net paise (vs Link: 0.20 * 20,000 = 4,000 - 1,000 = 3,000 net)
    assert res_boundary.selected_action == RecoveryAction.ESCALATE


def test_low_value_case_with_negative_intervention_ev_selects_no_action():
    engine = RecoveryDecisionEngine()
    case = make_case(amount_paise=3000)  # ₹30.00 ticket

    # Probabilities so low that intervention cost > expected gross recovery
    custom_probs = {
        RecoveryAction.NO_ACTION: 0.01,   # Gross = 30, Cost = 0, Net = 30 paise
        RecoveryAction.RETRY: 0.05,       # Gross = 150, Cost = 200, Net = -50 paise
        RecoveryAction.PAYMENT_LINK: 0.10, # Gross = 300, Cost = 1000, Net = -700 paise
        RecoveryAction.REMINDER: 0.05,    # Gross = 150, Cost = 500, Net = -350 paise
        RecoveryAction.ESCALATE: 0.20,    # Disqualified (micro ticket)
    }

    res = engine.evaluate_case(case, custom_probabilities=custom_probs)
    assert res.selected_action == RecoveryAction.NO_ACTION
    assert res.selected_expected_net_paise == 30


def test_exact_integer_floor_arithmetic():
    engine = RecoveryDecisionEngine()
    # Amount = 12,345 paise (₹123.45), P = 0.33333333
    # P * Amount = 4114.99995 -> floor gives 4,114 paise
    case = make_case(amount_paise=12345)
    custom_probs = {
        RecoveryAction.NO_ACTION: 0.0,
        RecoveryAction.RETRY: 0.33333333,
        RecoveryAction.PAYMENT_LINK: 0.0,
        RecoveryAction.REMINDER: 0.0,
        RecoveryAction.ESCALATE: 0.0,
    }

    res = engine.evaluate_case(case, custom_probabilities=custom_probs)
    retry_val = res.action_values[RecoveryAction.RETRY]
    assert isinstance(retry_val.expected_gross_paise, int)
    assert retry_val.expected_gross_paise == 4114
    assert retry_val.action_cost_paise == 200
    assert retry_val.expected_net_paise == 3914


def test_deterministic_tie_breaking():
    engine = RecoveryDecisionEngine()
    case = make_case(amount_paise=100000)

    # Make retry and reminder have exact identical expected net value
    # Retry: P=0.202, Gross=20,200, Cost=200, Net=20,000
    # Reminder: P=0.205, Gross=20,500, Cost=500, Net=20,000
    custom_probs = {
        RecoveryAction.NO_ACTION: 0.0,
        RecoveryAction.RETRY: 0.202,
        RecoveryAction.PAYMENT_LINK: 0.0,
        RecoveryAction.REMINDER: 0.205,
        RecoveryAction.ESCALATE: 0.0,
    }

    res1 = engine.evaluate_case(case, custom_probabilities=custom_probs)
    res2 = engine.evaluate_case(case, custom_probabilities=custom_probs)

    # Tie should deterministically select RETRY (earlier in ACTION_ORDER)
    assert res1.selected_action == RecoveryAction.RETRY
    assert res2.selected_action == RecoveryAction.RETRY
    assert res1.selected_action == res2.selected_action
