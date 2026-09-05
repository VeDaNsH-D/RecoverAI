"""
Scalable Benchmark Harness for RecoverAI Milestone 7: Scale Evaluation & Optimization.
Coordinates workload generation, vectorized batch inference, stage timing, memory profiling,
customer-clustered bootstrap uncertainty estimation, and machine-readable report export.
"""

from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from collections import Counter
import platform
import json
import time
import numpy as np
import pandas as pd
import sklearn

from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth
from simulator.policies.no_action import NoActionPolicy
from simulator.policies.rule_baseline import RuleBasedBaselinePolicy
from simulator.policies.oracle import OraclePolicy
from ml.models.bundle import MultiActionRecoveryModel, ACTION_ORDER, create_multi_action_model
from ml.decision_engine import RecoveryDecisionEngine
from ml.dataset import load_split_dataset_bundle
from ml.evaluation.schemas import (
    BenchmarkConfig,
    PolicyScaleMetrics,
    ReproducibilityManifest,
    ScaleBenchmarkReport,
    InferenceComparisonMetrics,
)
from ml.evaluation.workload import ScaleWorkload, generate_scale_workload, load_profile_workload
from ml.evaluation.bootstrap import CustomerClusteredBootstrap
from ml.evaluation.profiler import BenchmarkTimer, MemoryProfiler, benchmark_single_vs_batch_inference
from ml.evaluation.subgroups import analyze_policy_subgroups


class ScaleBenchmarkHarness:
    """
    Unified high-performance harness for evaluating RecoverAI policies at scale.
    """

    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.timer = BenchmarkTimer(num_cases=config.num_cases)
        self.mem_profiler = MemoryProfiler(num_cases=config.num_cases)

    def run_benchmark(
        self,
        workload: Optional[ScaleWorkload] = None,
        logistic_model: Optional[MultiActionRecoveryModel] = None,
        gbm_model: Optional[MultiActionRecoveryModel] = None,
        compare_single_batch: bool = False,
    ) -> ScaleBenchmarkReport:
        """
        Executes the full scale evaluation workflow.
        """
        self.mem_profiler.start()

        # 1. Stage: Workload Generation / Loading
        self.timer.start_stage("workload_generation")
        if workload is None:
            if self.config.profile in ("smoke", "standard", "stress", "large", "full"):
                workload = load_profile_workload(self.config.profile, seed=self.config.seed)
            else:
                workload = generate_scale_workload(
                    num_cases=self.config.num_cases,
                    seed=self.config.seed,
                    num_customers=self.config.num_customers,
                    profile_name=self.config.profile,
                )
        cases = workload.cases
        gt_map = workload.ground_truth_map
        n_cases = len(cases)
        self.timer.end_stage("workload_generation")

        # 2. Stage: Model Resolution
        self.timer.start_stage("model_resolution")
        if logistic_model is None:
            model_p = Path(self.config.model_source)
            if model_p.exists():
                logistic_model = MultiActionRecoveryModel.load(model_p)
            else:
                # Train fallback if artifact not present
                train_bundle = load_split_dataset_bundle(Path("data/sim_v1"), split="train")
                logistic_model = create_multi_action_model("logistic", calibrate=True, random_state=42).fit_all(train_bundle)

        logistic_engine = RecoveryDecisionEngine(model=logistic_model)
        self.timer.end_stage("model_resolution")

        # 3. Stage: Feature Extraction
        self.timer.start_stage("feature_extraction")
        X_matrix = logistic_engine.feature_extractor.transform_cases(cases)
        self.timer.end_stage("feature_extraction")

        # 4. Stage: Model Probability Inference
        self.timer.start_stage("model_inference")
        batch_probs = logistic_model.predict_all_positive_probas(X_matrix)
        self.timer.end_stage("model_inference")

        # 5. Stage: Vectorized Decision Selection
        self.timer.start_stage("decision_selection")
        logistic_actions = logistic_engine.select_actions_fast(cases, batch_probs=batch_probs)
        self.timer.end_stage("decision_selection")

        # Optional: Single vs Batch inference comparative benchmark
        inf_comparison: Optional[InferenceComparisonMetrics] = None
        if compare_single_batch:
            self.timer.start_stage("inference_comparison_benchmark")
            inf_comparison = benchmark_single_vs_batch_inference(logistic_engine, cases, sample_size=min(500, n_cases))
            self.timer.end_stage("inference_comparison_benchmark")

        # 6. Stage: Common Random Numbers (CRN) Outcome Evaluation across Policies
        self.timer.start_stage("outcome_simulation")

        # Policy Action Sets
        no_action_policy = NoActionPolicy()
        rule_policy = RuleBasedBaselinePolicy()
        oracle_policy = OraclePolicy(ground_truth_map=gt_map)

        no_action_acts = [no_action_policy.predict(c) for c in cases]
        rule_acts = [rule_policy.predict(c) for c in cases]
        oracle_acts = [oracle_policy.predict(c) for c in cases]

        policies_to_eval = [
            ("No Action", no_action_acts),
            ("Rule Baseline", rule_acts),
            ("Logistic Decision Engine (Champion)", logistic_actions),
        ]

        if gbm_model is not None:
            gbm_engine = RecoveryDecisionEngine(model=gbm_model)
            gbm_probs = gbm_model.predict_all_positive_probas(X_matrix)
            gbm_actions = gbm_engine.select_actions_fast(cases, batch_probs=gbm_probs)
            policies_to_eval.append(("GBM Decision Engine", gbm_actions))

        policies_to_eval.append(("Oracle (Benchmark Ceiling)", oracle_acts))

        # Vectorized outcome calculation using pre-computed ground truth arrays
        policy_outcomes: Dict[str, Dict[str, Any]] = {}

        for pol_name, acts in policies_to_eval:
            gross_arr = np.zeros(n_cases, dtype=np.int64)
            cost_arr = np.zeros(n_cases, dtype=np.int64)
            rec_flags = []
            act_counts = Counter()

            auto_count = 0
            esc_count = 0
            intervened_count = 0

            for i, (case, act) in enumerate(zip(cases, acts)):
                act_counts[act.value] += 1
                gt = gt_map[case.case_id]
                is_succ = bool(gt.potential_outcomes.get(act, 0) == 1)
                rec_flags.append(is_succ)

                rec_amt = case.amount_paise if is_succ else 0
                cost = int(ACTION_COSTS_PAISE[act])

                gross_arr[i] = rec_amt
                cost_arr[i] = cost

                if act in (RecoveryAction.RETRY, RecoveryAction.PAYMENT_LINK, RecoveryAction.REMINDER):
                    auto_count += 1
                elif act == RecoveryAction.ESCALATE:
                    esc_count += 1

                if act != RecoveryAction.NO_ACTION:
                    intervened_count += 1

            net_arr = gross_arr - cost_arr
            tot_gross = int(np.sum(gross_arr))
            tot_cost = int(np.sum(cost_arr))
            tot_net = int(np.sum(net_arr))
            tot_rec = int(np.sum(gross_arr > 0))

            policy_outcomes[pol_name] = {
                "gross_arr": gross_arr,
                "cost_arr": cost_arr,
                "net_arr": net_arr,
                "rec_flags": rec_flags,
                "tot_gross": tot_gross,
                "tot_cost": tot_cost,
                "tot_net": tot_net,
                "tot_rec": tot_rec,
                "actions": acts,
                "act_counts": dict(act_counts),
                "auto_count": auto_count,
                "esc_count": esc_count,
                "intervened_count": intervened_count,
            }

        self.timer.end_stage("outcome_simulation")

        # 7. Stage: Bootstrap Uncertainty Estimation
        bootstrap_cis: Dict[str, Dict[str, Any]] = {}
        if self.config.enable_bootstrap:
            self.timer.start_stage("customer_bootstrap")
            customer_ids = [c.customer_id for c in cases]
            bootstrapper = CustomerClusteredBootstrap(
                customer_ids=customer_ids,
                reps=self.config.bootstrap_reps,
                confidence_level=self.config.confidence_level,
                seed=self.config.seed,
            )
            rule_net_arr = policy_outcomes["Rule Baseline"]["net_arr"]

            for pol_name in policy_outcomes:
                g_arr = policy_outcomes[pol_name]["gross_arr"]
                c_arr = policy_outcomes[pol_name]["cost_arr"]
                base_net = rule_net_arr if pol_name != "Rule Baseline" else None
                cis = bootstrapper.compute_policy_confidence_intervals(
                    policy_gross_paise=g_arr,
                    policy_cost_paise=c_arr,
                    baseline_net_paise=base_net,
                )
                bootstrap_cis[pol_name] = cis

            self.timer.end_stage("customer_bootstrap")

        # 8. Stage: Subgroup Analysis
        self.timer.start_stage("subgroup_analysis")
        champ_outcomes = policy_outcomes["Logistic Decision Engine (Champion)"]
        subgroups = analyze_policy_subgroups(
            cases=cases,
            actions=champ_outcomes["actions"],
            recovered_flags=champ_outcomes["rec_flags"],
            net_paise_list=champ_outcomes["net_arr"].tolist(),
        )
        self.timer.end_stage("subgroup_analysis")

        # Memory Profiling Stop
        mem_metrics = self.mem_profiler.stop()

        # Build Policy Scale Metrics
        rule_net = policy_outcomes["Rule Baseline"]["tot_net"]
        oracle_net = policy_outcomes["Oracle (Benchmark Ceiling)"]["tot_net"]
        oracle_headroom_paise = max(1, oracle_net - rule_net)

        policy_metrics_map: Dict[str, PolicyScaleMetrics] = {}
        for pol_name, data in policy_outcomes.items():
            tot_net = data["tot_net"]
            delta_net = tot_net - rule_net
            regret = oracle_net - tot_net
            headroom_pct = (delta_net / oracle_headroom_paise) * 100.0 if oracle_headroom_paise > 0 else 0.0

            ci_data = bootstrap_cis.get(pol_name, {})

            pm = PolicyScaleMetrics(
                policy_name=pol_name,
                total_cases=n_cases,
                total_revenue_at_risk_paise=workload.total_revenue_at_risk_paise,
                gross_recovered_paise=data["tot_gross"],
                intervention_cost_paise=data["tot_cost"],
                net_recovered_paise=tot_net,
                delta_vs_rule_baseline_paise=delta_net,
                regret_vs_oracle_paise=regret,
                oracle_headroom_captured_pct=round(headroom_pct, 2),
                recovered_cases=data["tot_rec"],
                recovery_rate=round(data["tot_rec"] / n_cases, 4),
                intervened_cases=data["intervened_count"],
                intervention_rate=round(data["intervened_count"] / n_cases, 4),
                escalated_cases=data["esc_count"],
                escalation_rate=round(data["esc_count"] / n_cases, 4),
                intervention_efficiency=round(data["tot_rec"] / max(1, data["intervened_count"]), 4),
                action_counts=data["act_counts"],
                ci_net_recovered_inr=ci_data.get("net_recovered_inr"),
                ci_delta_vs_rule_inr=ci_data.get("delta_vs_rule_inr"),
                ci_recovery_rate_pct=ci_data.get("recovery_rate_pct"),
                ci_cost_inr=ci_data.get("cost_inr"),
            )
            policy_metrics_map[pol_name] = pm

        # Build Manifest
        manifest = ReproducibilityManifest(
            benchmark_version="1.0.0",
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            python_version=platform.python_version(),
            platform=platform.platform(),
            numpy_version=np.__version__,
            pandas_version=pd.__version__,
            scikit_learn_version=sklearn.__version__,
            model_source=self.config.model_source,
            action_costs_paise={a.value: int(ACTION_COSTS_PAISE[a]) for a in RecoveryAction},
            seed=self.config.seed,
            batch_size=self.config.batch_size,
        )

        # Performance summary
        total_elapsed_ms = sum(t.elapsed_ms for t in self.timer.stage_timings.values())
        overall_throughput = n_cases / max(1e-9, total_elapsed_ms / 1000.0)

        perf_summary = {
            "total_elapsed_ms": round(total_elapsed_ms, 2),
            "throughput_cases_per_sec": round(overall_throughput, 1),
            "memory": mem_metrics.model_dump(),
            "stage_timings": {name: t.model_dump() for name, t in self.timer.stage_timings.items()},
        }
        if inf_comparison is not None:
            perf_summary["batch_vs_single_comparison"] = inf_comparison.model_dump()

        dataset_meta = {
            "profile": workload.profile_name,
            "num_cases": workload.num_cases,
            "num_customers": workload.num_customers,
            "total_revenue_at_risk_paise": workload.total_revenue_at_risk_paise,
            "total_revenue_at_risk_inr": workload.total_revenue_at_risk_inr,
            "seed": workload.seed,
        }

        return ScaleBenchmarkReport(
            benchmark_id=f"scale_benchmark_{workload.profile_name}_{workload.num_cases}_{workload.seed}",
            dataset_metadata=dataset_meta,
            configuration=self.config,
            performance=perf_summary,
            policies=policy_metrics_map,
            subgroups=subgroups,
            reproducibility=manifest,
        )


def generate_markdown_report(report: ScaleBenchmarkReport) -> str:
    """Renders a comprehensive, GitHub-Flavored Markdown report from ScaleBenchmarkReport."""
    lines = []
    meta = report.dataset_metadata
    perf = report.performance
    mem = perf.get("memory", {})

    lines.append("# Milestone 7 Scale & Stress Benchmark Report — RecoverAI")
    lines.append("")
    lines.append("> **Scope Notice**: *This document reports computational scalability, latency, memory, and statistical uncertainty under synthetic scale workloads (Mode B). It does NOT replace the authoritative frozen `sim_v1` scientific benchmark.*")
    lines.append("")
    lines.append("## 1. Executive Workload & Performance Summary")
    lines.append("")
    lines.append(f"- **Workload Profile**: `{meta.get('profile', 'custom').upper()}`")
    lines.append(f"- **Scale Workload Size**: **{meta.get('num_cases', 0):,} Cases** across **{meta.get('num_customers', 0):,} Unique Customers**")
    lines.append(f"- **Total Revenue at Risk**: ₹{meta.get('total_revenue_at_risk_inr', 0.0):,.2f} ({meta.get('total_revenue_at_risk_paise', 0):,} paise)")
    lines.append(f"- **Total Benchmark Runtime**: **{perf.get('total_elapsed_ms', 0.0):,.2f} ms**")
    lines.append(f"- **Overall Pipeline Throughput**: **{perf.get('throughput_cases_per_sec', 0.0):,.1f} cases/sec**")
    lines.append(f"- **Peak Memory Allocated**: **{mem.get('peak_memory_mb', 0.0):.2f} MB** ({mem.get('memory_per_case_kb', 0.0):.3f} KB/case)")
    lines.append(f"- **Random Seed**: `{meta.get('seed', 42)}` (Common Random Numbers paired potential outcomes)")
    lines.append("")

    # Single vs Batch comparison
    if "batch_vs_single_comparison" in perf:
        comp = perf["batch_vs_single_comparison"]
        lines.append("### Single-Case vs. Batch Inference Comparison")
        lines.append("")
        lines.append("| Execution Mode | Total Latency | Latency / Case | Throughput | Speedup Factor |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        lines.append(f"| **Single-Case Reference Path** | {comp['single_total_ms']:,.2f} ms | {comp['single_latency_ms_per_case']:.4f} ms | {comp['single_throughput_cases_per_sec']:,.1f} cases/sec | 1.0x (Baseline) |")
        lines.append(f"| **Vectorized Batch Path** | {comp['batch_total_ms']:,.2f} ms | {comp['batch_latency_ms_per_case']:.4f} ms | {comp['batch_throughput_cases_per_sec']:,.1f} cases/sec | **{comp['speedup_factor']:.2f}x Faster** |")
        lines.append("")

    # Stage Timings Table
    lines.append("### Pipeline Stage Latency Breakdown")
    lines.append("")
    lines.append("| Stage Name | Elapsed Time (ms) | Mean Latency / Case (ms) | Throughput (cases/sec) |")
    lines.append("| :--- | :--- | :--- | :--- |")
    for st_name, st_data in perf.get("stage_timings", {}).items():
        lines.append(f"| `{st_name}` | {st_data['elapsed_ms']:,.2f} ms | {st_data['mean_ms_per_case']:.5f} ms | {st_data['throughput_cases_per_sec']:,.1f} |")
    lines.append("")

    # Policy Economic Comparison Table
    lines.append("## 2. Policy Economic & Decision Performance (CRN Paired)")
    lines.append("")
    lines.append("| Policy / Engine | Net Recovery (INR) | Gross Recovery (INR) | Cost (INR) | Delta vs Rule Baseline | Regret vs Oracle | Recovery Rate | Intervention Rate | Headroom % |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for p_name, pol in report.policies.items():
        net_str = f"₹{pol.net_recovered_inr:,.2f}"
        gross_str = f"₹{pol.gross_recovered_inr:,.2f}"
        cost_str = f"₹{pol.intervention_cost_inr:,.2f}"
        delta_str = f"+₹{pol.delta_vs_rule_baseline_inr:,.2f}" if pol.delta_vs_rule_baseline_paise >= 0 else f"-₹{abs(pol.delta_vs_rule_baseline_inr):,.2f}"
        if p_name == "Rule Baseline":
            delta_str = "--"
            headroom_str = "--"
        elif "Oracle" in p_name:
            headroom_str = "100.0%"
        else:
            headroom_str = f"{pol.oracle_headroom_captured_pct:.1f}%"

        regret_str = f"₹{pol.regret_vs_oracle_inr:,.2f}" if "Oracle" not in p_name else "₹0.00"

        lines.append(
            f"| **{p_name}** | {net_str} | {gross_str} | {cost_str} | {delta_str} | {regret_str} | {pol.recovery_rate:.1%} | {pol.intervention_rate:.1%} | {headroom_str} |"
        )
    lines.append("")

    # Confidence Intervals Table
    has_cis = any(p.ci_net_recovered_inr is not None for p in report.policies.values())
    if has_cis:
        lines.append("## 3. Customer-Clustered Bootstrap 95% Confidence Intervals")
        lines.append("")
        lines.append("> *Bootstrap clusters by `customer_id` (B=500 replicates) to capture customer-level variance.*")
        lines.append("")
        lines.append("| Policy | Net Recovery 95% CI (INR) | Delta vs Rule 95% CI (INR) | Recovery Rate 95% CI |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for p_name, pol in report.policies.items():
            ci_net = pol.ci_net_recovered_inr
            ci_delta = pol.ci_delta_vs_rule_inr
            ci_rec = pol.ci_recovery_rate_pct

            net_ci_str = f"[₹{ci_net.lower:,.2f}, ₹{ci_net.upper:,.2f}]" if ci_net else "N/A"
            delta_ci_str = f"[₹{ci_delta.lower:,.2f}, ₹{ci_delta.upper:,.2f}]" if ci_delta else "--"
            rec_ci_str = f"[{ci_rec.lower:.1f}%, {ci_rec.upper:.1f}%]" if ci_rec else "N/A"

            lines.append(f"| **{p_name}** | {net_ci_str} | {delta_ci_str} | {rec_ci_str} |")
        lines.append("")

    # Subgroups Table
    if report.subgroups:
        lines.append("## 4. Subgroup Stress & Segmentation Analysis (Champion Policy)")
        lines.append("")
        for dim_name, group_map in report.subgroups.items():
            lines.append(f"### Dimension: `{dim_name.replace('_', ' ').title()}`")
            lines.append("")
            lines.append("| Subgroup Segment | Cases (N) | Revenue at Risk (INR) | Net Recovery (INR) | Recovery Rate | Intervention Rate |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
            for grp_key, sm in group_map.items():
                lines.append(
                    f"| `{grp_key}` | {sm.num_cases:,} | ₹{sm.revenue_at_risk_inr:,.2f} | ₹{sm.net_recovered_inr:,.2f} | {sm.recovery_rate:.1%} | {sm.intervention_rate:.1%} |"
                )
            lines.append("")

    # Reproducibility Manifest
    rep = report.reproducibility
    lines.append("## 5. Reproducibility & Environment Manifest")
    lines.append("")
    lines.append(f"- **Benchmark Version**: `{rep.benchmark_version}`")
    lines.append(f"- **Execution Timestamp**: `{rep.timestamp}`")
    lines.append(f"- **Python Version**: `{rep.python_version}`")
    lines.append(f"- **Platform**: `{rep.platform}`")
    lines.append(f"- **NumPy Version**: `{rep.numpy_version}` | **pandas**: `{rep.pandas_version}` | **scikit-learn**: `{rep.scikit_learn_version}`")
    lines.append(f"- **Model Artifact**: `{rep.model_source}`")
    lines.append(f"- **Action Costs Configuration**: `{json.dumps(rep.action_costs_paise)}`")
    lines.append("")

    return "\n".join(lines) + "\n"
