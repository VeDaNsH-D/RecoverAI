"""
Tests for causal ground-truth mechanics, potential outcomes, and expected value equations.
"""

import pytest
from simulator.config import FailureType, RecoveryAction
from simulator.generators.customer_generator import generate_customers
from simulator.generators.case_generator import generate_cases
from simulator.generators.ground_truth_generator import generate_ground_truth
from simulator.schemas.ground_truth import CaseGroundTruth


def test_ground_truth_generation_completeness():
    customers = generate_customers(count=50, seed=42)
    cases = generate_cases(customers=customers, total_cases=100, seed=42)
    cust_map = {c.customer_id: c for c in customers}
    gt_map = generate_ground_truth(cases, cust_map, seed=42)

    assert len(gt_map) == len(cases)

    for case in cases:
        gt = gt_map.get(case.case_id)
        assert gt is not None
        assert isinstance(gt, CaseGroundTruth)
        assert gt.case_id == case.case_id
        assert gt.customer_id == case.customer_id

        # Verify all recovery actions have valid probabilities
        for action in RecoveryAction:
            assert action in gt.recovery_probabilities
            p = gt.recovery_probabilities[action]
            assert 0.0 <= p <= 1.0

            # Potential outcomes must be binary 0 or 1
            assert action in gt.potential_outcomes
            outcome = gt.potential_outcomes[action]
            assert outcome in (0, 1)

            # Expected net value is an integer (paise)
            assert action in gt.expected_net_values_paise
            assert isinstance(gt.expected_net_values_paise[action], int)

        # Latent variables
        assert 0.0 <= gt.latent_intent <= 1.0
        assert 0.0 <= gt.latent_funds_available <= 1.0

        # Optimal action is in action space
        assert gt.optimal_action in RecoveryAction
        assert isinstance(gt.is_recoverable_indicator, bool)


def test_causal_recovery_prob_relationships():
    """Verify that causal mechanisms reflect realistic domain logic."""
    customers = generate_customers(count=200, seed=42)
    cases = generate_cases(customers=customers, total_cases=500, seed=42)
    cust_map = {c.customer_id: c for c in customers}
    gt_map = generate_ground_truth(cases, cust_map, seed=42)

    # 1. For TEMPORARY_FAILURE, retry should have higher average success than for INVALID_PAYMENT_METHOD
    temp_cases = [c for c in cases if c.failure_type == FailureType.TEMPORARY_FAILURE]
    inv_cases = [c for c in cases if c.failure_type == FailureType.INVALID_PAYMENT_METHOD]

    avg_retry_prob_temp = sum(
        gt_map[c.case_id].recovery_probabilities[RecoveryAction.RETRY] for c in temp_cases
    ) / len(temp_cases)

    avg_retry_prob_inv = sum(
        gt_map[c.case_id].recovery_probabilities[RecoveryAction.RETRY] for c in inv_cases
    ) / len(inv_cases)

    assert avg_retry_prob_temp > avg_retry_prob_inv
    assert avg_retry_prob_inv < 0.15  # retrying a bad card/CVV rarely succeeds

    # 2. For INVALID_PAYMENT_METHOD, payment_link should have higher success than retry
    avg_link_prob_inv = sum(
        gt_map[c.case_id].recovery_probabilities[RecoveryAction.PAYMENT_LINK] for c in inv_cases
    ) / len(inv_cases)

    assert avg_link_prob_inv > avg_retry_prob_inv
