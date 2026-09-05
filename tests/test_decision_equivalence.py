"""
Decision Equivalence Gate Tests for RecoverAI Milestone 7.
Formally proves that the optimized vectorized decision path (select_actions_fast)
produces 100% identical selected actions and exact integer paise economic figures
as the reference object-based decision path (evaluate_case).
"""

import json
from pathlib import Path
import pytest
import numpy as np

from simulator.config import RecoveryAction, FailureType, PaymentMethod, ACTION_COSTS_PAISE
from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth
from simulator.outcome_simulator import OutcomeSimulator
from simulator.generators.customer_generator import generate_customers
from simulator.generators.case_generator import generate_cases
from ml.features import FeatureExtractor
from ml.models.bundle import MultiActionRecoveryModel, ACTION_ORDER
from ml.decision_engine import RecoveryDecisionEngine, MAX_RETRY_COUNT_ALLOWED, MIN_AMOUNT_PAISE_FOR_ESCALATE


@pytest.fixture(scope="module")
def champion_engine():
    model_path = Path("models/champion_recovery_model.pkl")
    model = MultiActionRecoveryModel.load(model_path)
    extractor = FeatureExtractor()
    return RecoveryDecisionEngine(model=model, feature_extractor=extractor)


def test_decision_equivalence_synthetic_cases(champion_engine):
    """Verify that select_actions_fast produces 100% identical actions to evaluate_case on synthetic cases."""
    customers = generate_customers(count=500, seed=42)
    cases = generate_cases(customers=customers, total_cases=1000, seed=142)

    # 1. Reference Path (evaluate_case one by one)
    reference_actions = [champion_engine.evaluate_case(c).selected_action for c in cases]
    reference_net_paise = [champion_engine.evaluate_case(c).selected_expected_net_paise for c in cases]

    # 2. Optimized Vectorized Path (select_actions_fast)
    optimized_actions = champion_engine.select_actions_fast(cases)

    # Gate 1: Exact Action Equivalence across all cases
    assert len(reference_actions) == len(optimized_actions) == 1000
    for idx, (ref_act, opt_act) in enumerate(zip(reference_actions, optimized_actions)):
        assert ref_act == opt_act, f"Action mismatch at case index {idx}: ref={ref_act.value}, opt={opt_act.value}"

    assert reference_actions == optimized_actions


def test_decision_equivalence_edge_cases_and_safety_boundaries(champion_engine):
    """Verify equivalence under extreme edge cases, safety boundaries, and ties."""
    edge_cases = [
        # Micro-ticket below ₹200 (ESCALATE must be disallowed)
        PaymentCase(
            case_id="edge_micro_1",
            customer_id="cust_001",
            merchant_id="merch_001",
            amount_paise=5000,  # ₹50 (< ₹200)
            currency="INR",
            payment_method=PaymentMethod.UPI,
            is_subscription=False,
            customer_historical_success_rate=0.9,
            customer_total_transactions=10,
            customer_total_failures=1,
            customer_avg_amount_paise=5000,
            customer_tenure_months=6,
            failure_type=FailureType.TEMPORARY_FAILURE,
            retry_count=0,
            hours_since_failure=0.5,
            created_at="2026-09-01T00:00:00Z",
        ),
        # Exactly at ₹200 boundary (ESCALATE allowed)
        PaymentCase(
            case_id="edge_micro_200",
            customer_id="cust_001",
            merchant_id="merch_001",
            amount_paise=20000,  # ₹200
            currency="INR",
            payment_method=PaymentMethod.CARD,
            is_subscription=True,
            customer_historical_success_rate=0.8,
            customer_total_transactions=20,
            customer_total_failures=4,
            customer_avg_amount_paise=20000,
            customer_tenure_months=12,
            failure_type=FailureType.INSUFFICIENT_FUNDS,
            retry_count=1,
            hours_since_failure=2.0,
            created_at="2026-09-01T00:00:00Z",
        ),
        # Retry count at boundary (retry_count = 2 -> RETRY disallowed)
        PaymentCase(
            case_id="edge_retry_2",
            customer_id="cust_002",
            merchant_id="merch_001",
            amount_paise=500000,
            currency="INR",
            payment_method=PaymentMethod.NETBANKING,
            is_subscription=False,
            customer_historical_success_rate=0.5,
            customer_total_transactions=5,
            customer_total_failures=3,
            customer_avg_amount_paise=500000,
            customer_tenure_months=2,
            failure_type=FailureType.INVALID_PAYMENT_METHOD,
            retry_count=2,
            hours_since_failure=24.0,
            created_at="2026-09-01T00:00:00Z",
        ),
        # High-value transaction (₹10,00,000 = 100,000,000 paise)
        PaymentCase(
            case_id="edge_high_val",
            customer_id="cust_003",
            merchant_id="merch_001",
            amount_paise=100_000_000,
            currency="INR",
            payment_method=PaymentMethod.MANDATE,
            is_subscription=True,
            customer_historical_success_rate=0.99,
            customer_total_transactions=100,
            customer_total_failures=1,
            customer_avg_amount_paise=100_000_000,
            customer_tenure_months=36,
            failure_type=FailureType.TEMPORARY_FAILURE,
            retry_count=0,
            hours_since_failure=0.1,
            created_at="2026-09-01T00:00:00Z",
        ),
    ]

    ref_actions = [champion_engine.evaluate_case(c).selected_action for c in edge_cases]
    opt_actions = champion_engine.select_actions_fast(edge_cases)

    assert ref_actions == opt_actions


def test_decision_equivalence_deterministic_tie_breaking(champion_engine):
    """Verify tie-breaking determinism when multiple actions produce identical expected net payoff."""
    case = PaymentCase(
        case_id="case_tie",
        customer_id="cust_tie",
        merchant_id="merch_001",
        amount_paise=100000,
        currency="INR",
        payment_method=PaymentMethod.UPI,
        is_subscription=False,
        customer_historical_success_rate=0.8,
        customer_total_transactions=10,
        customer_total_failures=2,
        customer_avg_amount_paise=100000,
        customer_tenure_months=6,
        failure_type=FailureType.TEMPORARY_FAILURE,
        retry_count=0,
        hours_since_failure=1.0,
        created_at="2026-09-01T00:00:00Z",
    )

    # Custom synthetic probabilities where NO_ACTION (cost=0) and RETRY (cost=200) yield identical net = 0
    # NO_ACTION: prob = 0.0 -> gross = 0 -> net = 0
    # RETRY: prob = 0.002 -> gross = 200 -> cost = 200 -> net = 0
    # PAYMENT_LINK: prob = 0.01 -> gross = 1000 -> cost = 1000 -> net = 0
    custom_probs = {
        RecoveryAction.NO_ACTION: np.array([0.0]),
        RecoveryAction.RETRY: np.array([0.002]),
        RecoveryAction.PAYMENT_LINK: np.array([0.01]),
        RecoveryAction.REMINDER: np.array([0.0]),
        RecoveryAction.ESCALATE: np.array([0.0]),
    }

    # evaluate_case reference
    ref_dict_probs = {k: float(v[0]) for k, v in custom_probs.items()}
    ref_res = champion_engine.evaluate_case(case, custom_probabilities=ref_dict_probs)

    # select_actions_fast optimized
    opt_act = champion_engine.select_actions_fast([case], batch_probs=custom_probs)[0]

    # Both must select NO_ACTION (first index in ACTION_ORDER)
    assert ref_res.selected_action == RecoveryAction.NO_ACTION
    assert opt_act == RecoveryAction.NO_ACTION
    assert ref_res.selected_action == opt_act


def test_decision_equivalence_frozen_test_split(champion_engine):
    """
    Critical Milestone 7 Regression Test:
    Proves that select_actions_fast produces 100% identical actions, identical outcomes,
    and exact integer paise financial results down to the single paise on the frozen
    1,500-case scientific benchmark (data/sim_v1/test).
    """
    test_dir = Path("data/sim_v1/test")
    assert (test_dir / "observable_cases.json").exists(), "Missing frozen test cases"
    assert (test_dir / "hidden_ground_truth.json").exists(), "Missing frozen ground truth"

    with open(test_dir / "observable_cases.json", "r", encoding="utf-8") as f:
        cases_raw = json.load(f)
        test_cases = [PaymentCase.model_validate(x) for x in cases_raw]

    with open(test_dir / "hidden_ground_truth.json", "r", encoding="utf-8") as f:
        gt_raw = json.load(f)
        test_gt = {cid: CaseGroundTruth.model_validate(x) for cid, x in gt_raw.items()}

    assert len(test_cases) == 1500

    # 1. Evaluate single-case reference path
    ref_decisions = [champion_engine.evaluate_case(c) for c in test_cases]
    ref_actions = [d.selected_action for d in ref_decisions]

    # 2. Evaluate fast vectorized batch path
    fast_actions = champion_engine.select_actions_fast(test_cases)

    # Assert 1: Exact case-by-case action equivalence across all 1,500 frozen cases
    assert len(ref_actions) == len(fast_actions) == 1500
    for idx, (ref_act, fast_act) in enumerate(zip(ref_actions, fast_actions)):
        assert ref_act == fast_act, f"Action mismatch at frozen test case {idx} ({test_cases[idx].case_id}): ref={ref_act.value}, fast={fast_act.value}"
    assert ref_actions == fast_actions

    # 3. Simulate Common Random Number outcomes under frozen ground truth
    simulator = OutcomeSimulator(ground_truth_map=test_gt)

    ref_sim_results = [simulator.execute_action(c, a) for c, a in zip(test_cases, ref_actions)]
    fast_sim_results = [simulator.execute_action(c, a) for c, a in zip(test_cases, fast_actions)]

    ref_gross_paise = sum(r.recovered_amount_paise for r in ref_sim_results)
    ref_cost_paise = sum(r.intervention_cost_paise for r in ref_sim_results)
    ref_net_paise = sum(r.net_recovered_amount_paise for r in ref_sim_results)
    ref_recovered_count = sum(1 for r in ref_sim_results if r.recovered)

    fast_gross_paise = sum(r.recovered_amount_paise for r in fast_sim_results)
    fast_cost_paise = sum(r.intervention_cost_paise for r in fast_sim_results)
    fast_net_paise = sum(r.net_recovered_amount_paise for r in fast_sim_results)
    fast_recovered_count = sum(1 for r in fast_sim_results if r.recovered)

    # Assert 2: Exact integer paise financial equality between reference and fast paths
    assert fast_gross_paise == ref_gross_paise
    assert fast_cost_paise == ref_cost_paise
    assert fast_net_paise == ref_net_paise
    assert fast_recovered_count == ref_recovered_count

    # Assert 3: Exact match with official frozen benchmark constants (reports/final_test_evaluation.json)
    # Revenue at Risk: ₹4,065,306.00 (406,530,600 paise)
    # Champion Gross: ₹2,972,057.00 (297,205,700 paise)
    # Champion Cost: ₹25,126.00 (2,512,600 paise)
    # Champion Net: ₹2,946,931.00 (294,693,100 paise)
    # Champion Recovered Count: 1,070 cases (71.33%)
    assert ref_gross_paise == 297_205_700, f"Expected 297,205,700 gross paise, got {ref_gross_paise}"
    assert ref_cost_paise == 2_512_600, f"Expected 2,512,600 cost paise, got {ref_cost_paise}"
    assert ref_net_paise == 294_693_100, f"Expected 294,693,100 net paise, got {ref_net_paise}"
    assert ref_recovered_count == 1070, f"Expected 1,070 recoveries, got {ref_recovered_count}"

    # Assert 4: Exact action distribution on frozen test set
    action_counts = dict()
    for a in fast_actions:
        action_counts[a] = action_counts.get(a, 0) + 1

    assert action_counts[RecoveryAction.RETRY] == 423
    assert action_counts[RecoveryAction.PAYMENT_LINK] == 602
    assert action_counts[RecoveryAction.REMINDER] == 122
    assert action_counts[RecoveryAction.ESCALATE] == 353
    assert action_counts.get(RecoveryAction.NO_ACTION, 0) == 0
