"""
Tests for deterministic seed reproducibility and Common Random Numbers (CRN).
"""

import pytest
from simulator.config import RecoveryAction
from simulator.generators.customer_generator import generate_customers
from simulator.generators.case_generator import generate_cases
from simulator.generators.ground_truth_generator import generate_ground_truth
from simulator.outcome_simulator import OutcomeSimulator
from simulator.evaluator import EvaluationEngine
from simulator.policies.no_action import NoActionPolicy
from simulator.policies.rule_baseline import RuleBasedBaselinePolicy
from simulator.policies.oracle import OraclePolicy


def test_seed_reproducibility_data_generation():
    """Generating dataset with seed=42 twice must yield identical objects."""
    cust_1 = generate_customers(count=50, seed=42)
    cust_2 = generate_customers(count=50, seed=42)
    assert [c.model_dump() for c in cust_1] == [c.model_dump() for c in cust_2]

    cases_1 = generate_cases(customers=cust_1, total_cases=100, seed=42)
    cases_2 = generate_cases(customers=cust_2, total_cases=100, seed=42)
    assert [c.model_dump() for c in cases_1] == [c.model_dump() for c in cases_2]

    cust_map_1 = {c.customer_id: c for c in cust_1}
    cust_map_2 = {c.customer_id: c for c in cust_2}

    gt_1 = generate_ground_truth(cases_1, cust_map_1, seed=42)
    gt_2 = generate_ground_truth(cases_2, cust_map_2, seed=42)
    assert {k: v.model_dump() for k, v in gt_1.items()} == {k: v.model_dump() for k, v in gt_2.items()}


def test_common_random_numbers_policy_invariance():
    """Evaluating policies on the same dataset evaluates on identical underlying potential outcomes."""
    customers = generate_customers(count=50, seed=42)
    cases = generate_cases(customers=customers, total_cases=100, seed=42)
    cust_map = {c.customer_id: c for c in customers}
    gt_map = generate_ground_truth(cases, cust_map, seed=42)

    sim = OutcomeSimulator(ground_truth_map=gt_map)
    evaluator = EvaluationEngine(simulator=sim)

    # Evaluate baseline in Run 1
    res_base_1 = evaluator.evaluate_policy(RuleBasedBaselinePolicy(), cases)

    # Evaluate other policies in between
    _ = evaluator.evaluate_policy(NoActionPolicy(), cases)
    _ = evaluator.evaluate_policy(OraclePolicy(gt_map), cases)

    # Evaluate baseline in Run 2
    res_base_2 = evaluator.evaluate_policy(RuleBasedBaselinePolicy(), cases)

    # Outcomes must be 100% identical
    assert res_base_1.gross_recovered_revenue_paise == res_base_2.gross_recovered_revenue_paise
    assert res_base_1.net_recovered_revenue_paise == res_base_2.net_recovered_revenue_paise
    assert res_base_1.recovered_cases == res_base_2.recovered_cases
    assert res_base_1.total_intervention_cost_paise == res_base_2.total_intervention_cost_paise


def test_potential_outcomes_consistency_across_actions():
    """For any case, executing the same action via different callers gives identical outcome."""
    customers = generate_customers(count=10, seed=42)
    cases = generate_cases(customers=customers, total_cases=20, seed=42)
    cust_map = {c.customer_id: c for c in customers}
    gt_map = generate_ground_truth(cases, cust_map, seed=42)

    sim = OutcomeSimulator(ground_truth_map=gt_map)

    for case in cases:
        gt = gt_map[case.case_id]
        for action in RecoveryAction:
            res1 = sim.execute_action(case, action)
            res2 = sim.execute_action(case, action)
            expected_outcome = bool(gt.potential_outcomes[action] == 1)
            
            assert res1.recovered == expected_outcome
            assert res2.recovered == expected_outcome
            assert res1.recovered_amount_paise == res2.recovered_amount_paise
            assert res1.net_recovered_amount_paise == res2.net_recovered_amount_paise
