"""
Tests for Customer-Clustered Bootstrap Uncertainty Estimation (Milestone 7).
Verifies deterministic seed replay, customer grouping preservation, and CI interval validity.
"""

import pytest
import numpy as np

from ml.evaluation.bootstrap import CustomerClusteredBootstrap


def test_customer_bootstrap_deterministic_replay():
    """Verify that fixing the seed produces 100% identical bootstrap confidence intervals."""
    # 20 cases across 5 customers
    customer_ids = [f"cust_{i % 5}" for i in range(20)]
    gross = np.array([50000 * (i % 3) for i in range(20)], dtype=np.int64)
    cost = np.array([1000 for _ in range(20)], dtype=np.int64)
    base_net = np.array([20000 for _ in range(20)], dtype=np.int64)

    boot1 = CustomerClusteredBootstrap(customer_ids=customer_ids, reps=100, seed=42)
    ci1 = boot1.compute_policy_confidence_intervals(gross, cost, baseline_net_paise=base_net)

    boot2 = CustomerClusteredBootstrap(customer_ids=customer_ids, reps=100, seed=42)
    ci2 = boot2.compute_policy_confidence_intervals(gross, cost, baseline_net_paise=base_net)

    assert ci1["net_recovered_inr"].lower == ci2["net_recovered_inr"].lower
    assert ci1["net_recovered_inr"].upper == ci2["net_recovered_inr"].upper
    assert ci1["delta_vs_rule_inr"].lower == ci2["delta_vs_rule_inr"].lower
    assert ci1["delta_vs_rule_inr"].upper == ci2["delta_vs_rule_inr"].upper
    assert ci1["recovery_rate_pct"].lower == ci2["recovery_rate_pct"].lower
    assert ci1["recovery_rate_pct"].upper == ci2["recovery_rate_pct"].upper


def test_customer_bootstrap_preserves_customer_clusters():
    """Verify that bootstrap clusters all cases for a sampled customer together."""
    customer_ids = ["cust_A", "cust_A", "cust_B", "cust_B", "cust_C"]
    boot = CustomerClusteredBootstrap(customer_ids=customer_ids, reps=50, seed=123)

    assert boot.num_unique_customers == 3
    assert len(boot.cust_to_case_indices["cust_A"]) == 2
    assert len(boot.cust_to_case_indices["cust_B"]) == 2
    assert len(boot.cust_to_case_indices["cust_C"]) == 1


def test_customer_bootstrap_ci_ordering_and_bounds():
    """Verify that CI lower bounds are strictly <= upper bounds and contain the point estimate."""
    customer_ids = [f"cust_{i % 10}" for i in range(100)]
    gross = np.random.default_rng(42).integers(0, 100000, size=100)
    cost = np.full(100, 1000, dtype=np.int64)

    point_net_inr = np.sum(gross - cost) / 100.0
    point_cost_inr = np.sum(cost) / 100.0
    point_rec_rate = (np.sum(gross > 0) / 100.0) * 100.0

    boot = CustomerClusteredBootstrap(customer_ids=customer_ids, reps=200, confidence_level=0.95, seed=42)
    cis = boot.compute_policy_confidence_intervals(policy_gross_paise=gross, policy_cost_paise=cost)

    ci_net = cis["net_recovered_inr"]
    ci_cost = cis["cost_inr"]
    ci_rec = cis["recovery_rate_pct"]

    # Lower <= Upper
    assert ci_net.lower <= ci_net.upper
    assert ci_cost.lower <= ci_cost.upper
    assert ci_rec.lower <= ci_rec.upper

    # Point estimate bounded within sensible range
    assert ci_net.lower <= point_net_inr <= ci_net.upper
    assert ci_cost.lower <= point_cost_inr <= ci_cost.upper
    assert ci_rec.lower <= point_rec_rate <= ci_rec.upper
