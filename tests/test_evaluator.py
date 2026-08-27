"""
Tests for financial calculations (integer paise) and evaluation engine metrics.
"""

import pytest
from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from simulator.generators.customer_generator import generate_customers
from simulator.generators.case_generator import generate_cases
from simulator.generators.ground_truth_generator import generate_ground_truth
from simulator.outcome_simulator import OutcomeSimulator
from simulator.evaluator import EvaluationEngine
from simulator.policies.no_action import NoActionPolicy
from simulator.policies.rule_baseline import RuleBasedBaselinePolicy
from simulator.policies.oracle import OraclePolicy


def test_evaluator_exact_integer_paise_accounting():
    customers = generate_customers(count=50, seed=42)
    cases = generate_cases(customers=customers, total_cases=100, seed=42)
    cust_map = {c.customer_id: c for c in customers}
    gt_map = generate_ground_truth(cases, cust_map, seed=42)

    sim = OutcomeSimulator(ground_truth_map=gt_map)
    evaluator = EvaluationEngine(simulator=sim)

    # 1. No Action policy has exactly zero intervention cost
    res_no_action = evaluator.evaluate_policy(NoActionPolicy(), cases)
    assert res_no_action.total_intervention_cost_paise == 0
    assert res_no_action.gross_recovered_revenue_paise == res_no_action.net_recovered_revenue_paise
    assert res_no_action.total_intervened_cases == 0
    assert res_no_action.automated_recovery_cases == 0
    assert res_no_action.escalated_cases == 0

    # 2. Rule Baseline policy accounting
    res_base = evaluator.evaluate_policy(RuleBasedBaselinePolicy(), cases)
    assert (
        res_base.net_recovered_revenue_paise
        == res_base.gross_recovered_revenue_paise - res_base.total_intervention_cost_paise
    )
    assert res_base.total_revenue_at_risk_paise == sum(c.amount_paise for c in cases)

    # 3. Multi-policy comparison & delta checks
    comparison = evaluator.evaluate_policies(
        policies=[NoActionPolicy(), RuleBasedBaselinePolicy(), OraclePolicy(gt_map)],
        cases=cases,
        split_name="test",
        baseline_policy_name="rule_baseline",
    )

    # Baseline delta vs baseline must be exactly 0
    base_eval = comparison.results["rule_baseline"]
    assert base_eval.incremental_net_revenue_vs_baseline_paise == 0

    # Oracle chooses the optimal expected value action for 100% of cases
    oracle_eval = comparison.results["oracle"]
    for case in cases:
        chosen = OraclePolicy(gt_map).predict(case)
        assert chosen == gt_map[case.case_id].optimal_action

    # Total expected net payoff of Oracle must be strictly >= Rule Baseline
    total_expected_oracle = sum(
        gt_map[c.case_id].expected_net_values_paise[gt_map[c.case_id].optimal_action]
        for c in cases
    )
    total_expected_baseline = sum(
        gt_map[c.case_id].expected_net_values_paise[RuleBasedBaselinePolicy().predict(c)]
        for c in cases
    )
    assert total_expected_oracle >= total_expected_baseline

    # Check report generation
    report = comparison.generate_console_report()
    assert "RECOVERAI EVALUATION REPORT" in report
    assert "rule_baseline" in report
    assert "oracle" in report


def test_calibration_analysis_metrics():
    """Verify that calibration analysis executes cleanly and computes expected gaps."""
    from simulator.calibration import analyze_calibration

    customers = generate_customers(count=50, seed=42)
    cases = generate_cases(customers=customers, total_cases=100, seed=42)
    cust_map = {c.customer_id: c for c in customers}
    gt_map = generate_ground_truth(cases, cust_map, seed=42)

    cal = analyze_calibration(cases, gt_map)
    assert cal.total_cases == 100
    assert cal.total_revenue_at_risk_paise == sum(c.amount_paise for c in cases)
    assert cal.expected_headroom_paise >= 0
    assert len(cal.mean_recovery_probabilities) == 5
    assert len(cal.optimal_action_counts) == 5
    assert isinstance(cal.generate_console_report(), str)
