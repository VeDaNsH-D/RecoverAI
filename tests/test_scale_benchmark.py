"""
Integration and Unit Tests for RecoverAI Milestone 7 Scale Benchmark Suite.
Verifies workload generation, harness execution, stage timings, memory profiling, and manifest integrity.
"""

from pathlib import Path
import pytest
import numpy as np

from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from ml.models.bundle import MultiActionRecoveryModel
from ml.evaluation.schemas import BenchmarkConfig, ScaleBenchmarkReport
from ml.evaluation.workload import (
    generate_scale_workload,
    load_profile_workload,
    WORKLOAD_PROFILES,
)
from ml.evaluation.harness import ScaleBenchmarkHarness, generate_markdown_report


@pytest.fixture(scope="module")
def champion_model():
    model_path = Path("models/champion_recovery_model.pkl")
    return MultiActionRecoveryModel.load(model_path)


def test_scale_workload_generation_properties():
    """Verify that scale workloads generate deterministic cases and isolated ground truth."""
    workload = generate_scale_workload(num_cases=500, seed=42, num_customers=100, profile_name="test_500")

    assert workload.num_cases == 500
    assert workload.num_customers == 100
    assert len(workload.cases) == 500
    assert len(workload.customers) == 100
    assert len(workload.ground_truth_map) == 500
    assert workload.total_revenue_at_risk_paise == sum(c.amount_paise for c in workload.cases)

    # Customer ID disjointness check
    cust_ids = {c.customer_id for c in workload.customers}
    for case in workload.cases:
        assert case.customer_id in cust_ids


def test_workload_profile_loader():
    """Verify standard workload profile presets load expected dimensions."""
    for prof in ["smoke", "standard"]:
        w = load_profile_workload(prof, seed=42)
        expected = WORKLOAD_PROFILES[prof]
        assert w.num_cases == expected["cases"]
        assert w.num_customers == expected["customers"]
        assert w.profile_name == prof


def test_scale_benchmark_harness_end_to_end(champion_model):
    """Verify end-to-end execution of ScaleBenchmarkHarness with bootstrap, timing, and memory metrics."""
    config = BenchmarkConfig(
        profile="smoke",
        num_cases=1000,
        num_customers=200,
        seed=42,
        batch_size=512,
        enable_bootstrap=True,
        bootstrap_reps=100,
    )

    harness = ScaleBenchmarkHarness(config)
    report = harness.run_benchmark(logistic_model=champion_model, compare_single_batch=False)

    assert isinstance(report, ScaleBenchmarkReport)
    assert report.configuration.num_cases == 1000

    # 1. Economic accounting assertions
    for pol_name, pol_metrics in report.policies.items():
        assert pol_metrics.total_cases == 1000
        assert pol_metrics.net_recovered_paise == pol_metrics.gross_recovered_paise - pol_metrics.intervention_cost_paise
        assert 0.0 <= pol_metrics.recovery_rate <= 1.0
        assert 0.0 <= pol_metrics.intervention_rate <= 1.0

    # 2. Delta vs Rule assertions
    rule_net = report.policies["Rule Baseline"].net_recovered_paise
    logistic_net = report.policies["Logistic Decision Engine (Champion)"].net_recovered_paise
    assert report.policies["Logistic Decision Engine (Champion)"].delta_vs_rule_baseline_paise == logistic_net - rule_net
    assert report.policies["Rule Baseline"].delta_vs_rule_baseline_paise == 0

    # 3. Profiler stage timing assertions
    stage_timings = report.performance["stage_timings"]
    assert "feature_extraction" in stage_timings
    assert "model_inference" in stage_timings
    assert "decision_selection" in stage_timings
    assert "outcome_simulation" in stage_timings
    assert "customer_bootstrap" in stage_timings
    assert "subgroup_analysis" in stage_timings

    # 4. Memory metrics assertions
    mem = report.performance["memory"]
    assert mem["peak_memory_mb"] > 0
    assert mem["memory_per_case_kb"] >= 0

    # 5. Reproducibility manifest assertions
    manifest = report.reproducibility
    assert manifest.seed == 42
    assert manifest.action_costs_paise[RecoveryAction.NO_ACTION.value] == int(ACTION_COSTS_PAISE[RecoveryAction.NO_ACTION])
    assert manifest.action_costs_paise[RecoveryAction.RETRY.value] == int(ACTION_COSTS_PAISE[RecoveryAction.RETRY])
    assert manifest.action_costs_paise[RecoveryAction.PAYMENT_LINK.value] == int(ACTION_COSTS_PAISE[RecoveryAction.PAYMENT_LINK])
    assert manifest.action_costs_paise[RecoveryAction.REMINDER.value] == int(ACTION_COSTS_PAISE[RecoveryAction.REMINDER])
    assert manifest.action_costs_paise[RecoveryAction.ESCALATE.value] == int(ACTION_COSTS_PAISE[RecoveryAction.ESCALATE])

    # 6. Subgroups assertions
    subgroups = report.subgroups
    assert "failure_type" in subgroups
    assert "payment_method" in subgroups
    assert "retry_count" in subgroups
    assert "subscription" in subgroups
    assert "amount_tier" in subgroups
    assert "customer_success_tier" in subgroups

    # 7. Markdown report generation test
    md_report = generate_markdown_report(report)
    assert "# Milestone 7 Scale & Stress Benchmark Report" in md_report
    assert "Policy / Engine" in md_report
    assert "Customer-Clustered Bootstrap" in md_report
