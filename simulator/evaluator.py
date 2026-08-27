"""
Evaluation Engine for RecoverAI.
Computes primary (Incremental Net Revenue) and secondary metrics across policies.
All internal monetary calculations are conducted in integer paise.
"""

from typing import Dict, List, Optional
import json
from pydantic import BaseModel, Field

from simulator.config import RecoveryAction
from simulator.schemas.case import PaymentCase
from simulator.schemas.action_result import InterventionResult
from simulator.outcome_simulator import OutcomeSimulator
from simulator.policies.base import BasePolicy


class PolicyEvaluationResult(BaseModel):
    """
    Evaluation metrics for a single policy evaluated over a dataset.
    """
    policy_name: str
    total_cases: int
    total_revenue_at_risk_paise: int
    
    # Financial results in integer paise
    gross_recovered_revenue_paise: int
    total_intervention_cost_paise: int
    net_recovered_revenue_paise: int
    incremental_net_revenue_vs_baseline_paise: int = 0
    incremental_gross_revenue_vs_baseline_paise: int = 0

    # Counts & Rates
    recovered_cases: int
    recovery_rate_pct: float
    
    # Intervention breakdown
    automated_recovery_cases: int
    automated_recovery_rate_pct: float
    escalated_cases: int
    escalation_rate_pct: float
    total_intervened_cases: int
    total_intervention_rate_pct: float

    # Efficiency (Successful actions / attempted actions)
    automated_recovery_efficiency_pct: float
    escalation_efficiency_pct: float
    overall_intervention_efficiency_pct: float
    
    # Latency & Averages
    average_recovered_amount_paise: int
    average_recovery_latency_hours: float

    # Action breakdowns
    action_counts: Dict[str, int]
    action_percentages: Dict[str, float]
    action_success_counts: Dict[str, int]
    action_success_rates_pct: Dict[str, float]

    # Presentation Helpers (in INR)
    @property
    def total_revenue_at_risk_inr(self) -> float:
        return self.total_revenue_at_risk_paise / 100.0

    @property
    def gross_recovered_revenue_inr(self) -> float:
        return self.gross_recovered_revenue_paise / 100.0

    @property
    def total_intervention_cost_inr(self) -> float:
        return self.total_intervention_cost_paise / 100.0

    @property
    def net_recovered_revenue_inr(self) -> float:
        return self.net_recovered_revenue_paise / 100.0

    @property
    def incremental_net_revenue_vs_baseline_inr(self) -> float:
        return self.incremental_net_revenue_vs_baseline_paise / 100.0


class MultiPolicyComparison(BaseModel):
    """
    Side-by-side comparison of multiple policies evaluated on the same potential outcomes.
    """
    split_name: str
    total_cases: int
    total_revenue_at_risk_paise: int
    baseline_policy_name: str
    results: Dict[str, PolicyEvaluationResult]

    def to_json_str(self, indent: int = 2) -> str:
        """Serializes comparison to formatted JSON."""
        return json.dumps(self.model_dump(), indent=indent)

    def generate_console_report(self) -> str:
        """
        Generates a clean, human-readable terminal table comparing policies.
        """
        lines = []
        lines.append("=" * 115)
        lines.append(f" RECOVERAI EVALUATION REPORT -- SPLIT: {self.split_name.upper()}")
        lines.append(f" Total Cases: {self.total_cases:,} | Total Revenue at Risk: INR {self.total_revenue_at_risk_paise / 100:,.2f} ({self.total_revenue_at_risk_paise:,} paise)")
        lines.append(f" Benchmark Baseline: {self.baseline_policy_name}")
        lines.append("=" * 115)

        # Header
        headers = [
            "Policy",
            "Net Rec (INR)",
            "Delta Net vs Base",
            "Gross Rec (INR)",
            "Cost (INR)",
            "Rec %",
            "Auto %",
            "Esc %",
            "Eff %",
            "Avg Latency",
        ]
        row_fmt = "{:<16} | {:>18} | {:>18} | {:>16} | {:>10} | {:>6} | {:>6} | {:>6} | {:>6} | {:>11}"
        lines.append(row_fmt.format(*headers))
        lines.append("-" * 115)

        for name, res in self.results.items():
            delta_str = f"{res.incremental_net_revenue_vs_baseline_inr:+,.2f}" if name != self.baseline_policy_name else "0.00 (Base)"
            row = [
                res.policy_name,
                f"INR {res.net_recovered_revenue_inr:,.2f}",
                delta_str,
                f"INR {res.gross_recovered_revenue_inr:,.2f}",
                f"INR {res.total_intervention_cost_inr:,.2f}",
                f"{res.recovery_rate_pct:.1f}%",
                f"{res.automated_recovery_rate_pct:.1f}%",
                f"{res.escalation_rate_pct:.1f}%",
                f"{res.overall_intervention_efficiency_pct:.1f}%",
                f"{res.average_recovery_latency_hours:.1f} hrs",
            ]
            lines.append(row_fmt.format(*row))

        lines.append("=" * 115)
        lines.append("\nACTION DISTRIBUTION BREAKDOWN:")
        action_row_fmt = "{:<16} | " + " | ".join(["{:>15}"] * len(RecoveryAction))
        action_names = [a.value for a in RecoveryAction]
        lines.append(action_row_fmt.format("Policy", *[f"{a} (%)" for a in action_names]))
        lines.append("-" * 115)

        for name, res in self.results.items():
            pcts = [f"{res.action_percentages.get(a, 0.0):.1f}%" for a in action_names]
            lines.append(action_row_fmt.format(name, *pcts))

        lines.append("=" * 115)
        return "\n".join(lines)


class EvaluationEngine:
    """
    Evaluates recovery policies against an OutcomeSimulator holding ground-truth potential outcomes.
    """

    def __init__(self, simulator: OutcomeSimulator):
        self._simulator = simulator

    def evaluate_policy(
        self,
        policy: BasePolicy,
        cases: List[PaymentCase],
        baseline_result: Optional[PolicyEvaluationResult] = None,
    ) -> PolicyEvaluationResult:
        """
        Runs a policy over a list of observable cases and calculates all metrics.
        """
        if not cases:
            raise ValueError("Evaluation cases list cannot be empty.")

        total_cases = len(cases)
        total_risk_paise = sum(c.amount_paise for c in cases)

        gross_recovered_paise = 0
        total_cost_paise = 0
        recovered_cases_count = 0
        
        # Categorized action counts
        auto_intervened_count = 0
        auto_success_count = 0
        escalated_count = 0
        escalated_success_count = 0
        
        total_latency_hours = 0.0

        action_counts: Dict[str, int] = {a.value: 0 for a in RecoveryAction}
        action_success_counts: Dict[str, int] = {a.value: 0 for a in RecoveryAction}

        for case in cases:
            action = policy.predict(case)
            result = self._simulator.execute_action(case, action)

            act_str = action.value
            action_counts[act_str] += 1

            if result.recovered:
                gross_recovered_paise += result.recovered_amount_paise
                recovered_cases_count += 1
                action_success_counts[act_str] += 1
                total_latency_hours += result.recovery_latency_hours

            total_cost_paise += result.intervention_cost_paise

            # Categorize actions
            if action in (RecoveryAction.RETRY, RecoveryAction.PAYMENT_LINK, RecoveryAction.REMINDER):
                auto_intervened_count += 1
                if result.recovered:
                    auto_success_count += 1
            elif action == RecoveryAction.ESCALATE:
                escalated_count += 1
                if result.recovered:
                    escalated_success_count += 1

        net_recovered_paise = gross_recovered_paise - total_cost_paise
        recovery_rate_pct = (recovered_cases_count / total_cases) * 100.0
        
        auto_rate_pct = (auto_intervened_count / total_cases) * 100.0
        escalate_rate_pct = (escalated_count / total_cases) * 100.0
        total_intervened_count = auto_intervened_count + escalated_count
        total_intervene_rate_pct = (total_intervened_count / total_cases) * 100.0

        auto_efficiency_pct = (auto_success_count / max(1, auto_intervened_count)) * 100.0
        escalate_efficiency_pct = (escalated_success_count / max(1, escalated_count)) * 100.0
        overall_efficiency_pct = (
            (auto_success_count + escalated_success_count) / max(1, total_intervened_count)
        ) * 100.0
        
        avg_recovered_amount = (
            gross_recovered_paise // recovered_cases_count if recovered_cases_count > 0 else 0
        )
        avg_latency = (
            total_latency_hours / recovered_cases_count if recovered_cases_count > 0 else 0.0
        )

        action_percentages = {
            a: round((count / total_cases) * 100.0, 2) for a, count in action_counts.items()
        }
        action_success_rates = {
            a: round((action_success_counts[a] / max(1, action_counts[a])) * 100.0, 2)
            for a in action_counts
        }

        # Incremental calculations
        delta_net_paise = 0
        delta_gross_paise = 0
        if baseline_result is not None:
            delta_net_paise = net_recovered_paise - baseline_result.net_recovered_revenue_paise
            delta_gross_paise = gross_recovered_paise - baseline_result.gross_recovered_revenue_paise

        return PolicyEvaluationResult(
            policy_name=policy.name,
            total_cases=total_cases,
            total_revenue_at_risk_paise=total_risk_paise,
            gross_recovered_revenue_paise=gross_recovered_paise,
            total_intervention_cost_paise=total_cost_paise,
            net_recovered_revenue_paise=net_recovered_paise,
            incremental_net_revenue_vs_baseline_paise=delta_net_paise,
            incremental_gross_revenue_vs_baseline_paise=delta_gross_paise,
            recovered_cases=recovered_cases_count,
            recovery_rate_pct=round(recovery_rate_pct, 2),
            automated_recovery_cases=auto_intervened_count,
            automated_recovery_rate_pct=round(auto_rate_pct, 2),
            escalated_cases=escalated_count,
            escalation_rate_pct=round(escalate_rate_pct, 2),
            total_intervened_cases=total_intervened_count,
            total_intervention_rate_pct=round(total_intervene_rate_pct, 2),
            automated_recovery_efficiency_pct=round(auto_efficiency_pct, 2),
            escalation_efficiency_pct=round(escalate_efficiency_pct, 2),
            overall_intervention_efficiency_pct=round(overall_efficiency_pct, 2),
            average_recovered_amount_paise=avg_recovered_amount,
            average_recovery_latency_hours=round(avg_latency, 2),
            action_counts=action_counts,
            action_percentages=action_percentages,
            action_success_counts=action_success_counts,
            action_success_rates_pct=action_success_rates,
        )

    def evaluate_policies(
        self,
        policies: List[BasePolicy],
        cases: List[PaymentCase],
        split_name: str = "test",
        baseline_policy_name: str = "rule_baseline",
    ) -> MultiPolicyComparison:
        """
        Evaluates a set of policies on the exact same potential outcomes and computes deltas.
        """
        results_map: Dict[str, PolicyEvaluationResult] = {}

        # 1. Run all policies first
        for policy in policies:
            res = self.evaluate_policy(policy, cases, baseline_result=None)
            results_map[policy.name] = res

        # 2. Re-compute incremental delta against baseline if baseline exists
        baseline_res = results_map.get(baseline_policy_name)
        if baseline_res is not None:
            updated_results: Dict[str, PolicyEvaluationResult] = {}
            for name, res in results_map.items():
                updated_res = res.model_copy(
                    update={
                        "incremental_net_revenue_vs_baseline_paise": (
                            res.net_recovered_revenue_paise - baseline_res.net_recovered_revenue_paise
                        ),
                        "incremental_gross_revenue_vs_baseline_paise": (
                            res.gross_recovered_revenue_paise - baseline_res.gross_recovered_revenue_paise
                        ),
                    }
                )
                updated_results[name] = updated_res
            results_map = updated_results

        total_risk = sum(c.amount_paise for c in cases)
        return MultiPolicyComparison(
            split_name=split_name,
            total_cases=len(cases),
            total_revenue_at_risk_paise=total_risk,
            baseline_policy_name=baseline_policy_name,
            results=results_map,
        )
