"""
Calibration analysis and reporting for RecoverAI simulation environment.
Analyzes recovery probabilities, action optimality distributions, value gaps, and subgroup stats.
All monetary values are calculated in integer paise.
"""

from typing import Dict, List, Any
import numpy as np
from pydantic import BaseModel

from simulator.config import FailureType, PaymentMethod, RecoveryAction, ACTION_COSTS_PAISE
from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth
from simulator.policies.rule_baseline import RuleBasedBaselinePolicy


class CalibrationReport(BaseModel):
    """
    Structured calibration report for diagnosing simulation dynamics and economic headroom.
    """
    total_cases: int
    total_revenue_at_risk_paise: int
    
    # Probabilities by action
    mean_recovery_probabilities: Dict[str, float]
    p10_recovery_probabilities: Dict[str, float]
    p50_recovery_probabilities: Dict[str, float]
    p90_recovery_probabilities: Dict[str, float]

    # Action optimality distribution
    optimal_action_counts: Dict[str, int]
    optimal_action_percentages: Dict[str, float]
    no_action_optimal_pct: float

    # Action value gap (difference between best and second-best expected net value in paise)
    mean_action_value_gap_paise: int
    median_action_value_gap_paise: int
    p25_action_value_gap_paise: int
    p75_action_value_gap_paise: int

    # Baseline vs Oracle Expected Value Gap (Theoretical headroom in expected net payoff)
    total_expected_oracle_net_paise: int
    total_expected_baseline_net_paise: int
    expected_headroom_paise: int
    expected_headroom_pct: float

    # Recovery rates by subgroup
    recovery_by_failure_type: Dict[str, Dict[str, Any]]
    recovery_by_customer_reliability: Dict[str, Dict[str, Any]]
    recovery_by_amount_bucket: Dict[str, Dict[str, Any]]

    def generate_console_report(self) -> str:
        lines = []
        lines.append("=" * 95)
        lines.append(" RECOVERAI SIMULATOR CALIBRATION REPORT")
        lines.append(f" Total Cases Analyzed: {self.total_cases:,} | Total Risk: INR {self.total_revenue_at_risk_paise / 100:,.2f}")
        lines.append("=" * 95)

        lines.append("\n1. ACTION RECOVERY PROBABILITY DISTRIBUTION:")
        prob_fmt = "{:<16} | {:>10} | {:>10} | {:>10} | {:>10}"
        lines.append(prob_fmt.format("Action", "Mean", "P10", "Median (P50)", "P90"))
        lines.append("-" * 65)
        for act in RecoveryAction:
            a_str = act.value
            lines.append(prob_fmt.format(
                a_str,
                f"{self.mean_recovery_probabilities.get(a_str, 0.0):.3f}",
                f"{self.p10_recovery_probabilities.get(a_str, 0.0):.3f}",
                f"{self.p50_recovery_probabilities.get(a_str, 0.0):.3f}",
                f"{self.p90_recovery_probabilities.get(a_str, 0.0):.3f}",
            ))

        lines.append("\n2. OPTIMAL ACTION DISTRIBUTION (Ground-Truth Maximizer):")
        opt_fmt = "{:<16} | {:>10} | {:>12}"
        lines.append(opt_fmt.format("Action", "Count", "Percentage"))
        lines.append("-" * 45)
        for act in RecoveryAction:
            a_str = act.value
            cnt = self.optimal_action_counts.get(a_str, 0)
            pct = self.optimal_action_percentages.get(a_str, 0.0)
            lines.append(opt_fmt.format(a_str, f"{cnt:,}", f"{pct:.1f}%"))
        lines.append(f"-> NO_ACTION Optimal Proportion: {self.no_action_optimal_pct:.1f}%")

        lines.append("\n3. ECONOMIC DECISION HEADROOM (Expected Net Payoff):")
        lines.append(f" Total Oracle Expected Net:    INR {self.total_expected_oracle_net_paise / 100:,.2f}")
        lines.append(f" Total Baseline Expected Net:  INR {self.total_expected_baseline_net_paise / 100:,.2f}")
        lines.append(f" Theoretical Expected Headroom: INR {self.expected_headroom_paise / 100:,.2f} (+{self.expected_headroom_pct:.2f}% over baseline)")
        lines.append(f" Mean Action-Value Gap (1st vs 2nd Best Action): INR {self.mean_action_value_gap_paise / 100:,.2f} (Median: INR {self.median_action_value_gap_paise / 100:,.2f})")

        lines.append("\n4. SUBGROUP RECOVERY POTENTIAL (Optimal Action Expected Recovery):")
        sub_fmt = "{:<28} | {:>8} | {:>14} | {:>18}"
        lines.append(sub_fmt.format("Subgroup", "Cases", "Mean Rec Prob", "Mean Risk (INR)"))
        lines.append("-" * 75)
        
        lines.append(" [By Failure Type]")
        for ft_name, data in self.recovery_by_failure_type.items():
            lines.append(sub_fmt.format(
                f"  {ft_name}",
                f"{data['count']:,}",
                f"{data['mean_optimal_prob']:.1%}",
                f"INR {data['mean_amount_inr']:,.2f}",
            ))

        lines.append(" [By Customer Reliability]")
        for rel_name, data in self.recovery_by_customer_reliability.items():
            lines.append(sub_fmt.format(
                f"  {rel_name}",
                f"{data['count']:,}",
                f"{data['mean_optimal_prob']:.1%}",
                f"INR {data['mean_amount_inr']:,.2f}",
            ))

        lines.append(" [By Transaction Amount Tier]")
        for amt_tier, data in self.recovery_by_amount_bucket.items():
            lines.append(sub_fmt.format(
                f"  {amt_tier}",
                f"{data['count']:,}",
                f"{data['mean_optimal_prob']:.1%}",
                f"INR {data['mean_amount_inr']:,.2f}",
            ))

        lines.append("=" * 95)
        return "\n".join(lines)


def analyze_calibration(
    cases: List[PaymentCase],
    ground_truth_map: Dict[str, CaseGroundTruth],
) -> CalibrationReport:
    """
    Computes diagnostic calibration metrics on a dataset and ground truth map.
    """
    total_cases = len(cases)
    total_risk_paise = sum(c.amount_paise for c in cases)
    baseline_policy = RuleBasedBaselinePolicy()

    # 1. Probability distributions
    all_actions = list(RecoveryAction)
    prob_by_action: Dict[str, List[float]] = {a.value: [] for a in all_actions}
    optimal_action_counts: Dict[str, int] = {a.value: 0 for a in all_actions}
    action_gaps: List[int] = []

    total_oracle_expected_net = 0
    total_baseline_expected_net = 0

    # Subgroup aggregators
    ft_groups: Dict[str, List[Dict[str, Any]]] = {}
    rel_groups: Dict[str, List[Dict[str, Any]]] = {
        "Low (< 70%)": [],
        "Medium (70% - 85%)": [],
        "High (> 85%)": [],
    }
    amt_groups: Dict[str, List[Dict[str, Any]]] = {
        "Micro (< INR 500)": [],
        "Small (INR 500 - 1.5k)": [],
        "Medium (INR 1.5k - 5k)": [],
        "Large (INR 5k - 20k)": [],
        "Enterprise (> INR 20k)": [],
    }

    for case in cases:
        gt = ground_truth_map[case.case_id]
        
        # Probabilities
        for act in all_actions:
            p = gt.recovery_probabilities[act]
            prob_by_action[act.value].append(p)

        # Optimal action count
        opt_act_str = gt.optimal_action.value
        optimal_action_counts[opt_act_str] += 1

        # Action value gap (difference between top 2 expected net values)
        sorted_evs = sorted(gt.expected_net_values_paise.values(), reverse=True)
        best_ev = sorted_evs[0]
        second_ev = sorted_evs[1] if len(sorted_evs) > 1 else 0
        gap = max(0, best_ev - second_ev)
        action_gaps.append(gap)

        # Expected totals
        total_oracle_expected_net += best_ev
        base_act = baseline_policy.predict(case)
        total_baseline_expected_net += gt.expected_net_values_paise[base_act]

        # Subgroup stats
        opt_prob = gt.recovery_probabilities[gt.optimal_action]
        record = {
            "case_id": case.case_id,
            "amount_paise": case.amount_paise,
            "opt_prob": opt_prob,
        }

        # Failure type
        ft_name = case.failure_type.value
        if ft_name not in ft_groups:
            ft_groups[ft_name] = []
        ft_groups[ft_name].append(record)

        # Reliability
        succ = case.customer_historical_success_rate
        if succ < 0.70:
            rel_groups["Low (< 70%)"].append(record)
        elif succ <= 0.85:
            rel_groups["Medium (70% - 85%)"].append(record)
        else:
            rel_groups["High (> 85%)"].append(record)

        # Amount Tier
        amt_inr = case.amount_inr
        if amt_inr < 500:
            amt_groups["Micro (< INR 500)"].append(record)
        elif amt_inr < 1500:
            amt_groups["Small (INR 500 - 1.5k)"].append(record)
        elif amt_inr < 5000:
            amt_groups["Medium (INR 1.5k - 5k)"].append(record)
        elif amt_inr < 20000:
            amt_groups["Large (INR 5k - 20k)"].append(record)
        else:
            amt_groups["Enterprise (> INR 20k)"].append(record)

    # Calculate summary metrics
    mean_probs = {a: float(np.mean(vals)) for a, vals in prob_by_action.items()}
    p10_probs = {a: float(np.percentile(vals, 10)) for a, vals in prob_by_action.items()}
    p50_probs = {a: float(np.percentile(vals, 50)) for a, vals in prob_by_action.items()}
    p90_probs = {a: float(np.percentile(vals, 90)) for a, vals in prob_by_action.items()}

    optimal_pcts = {
        a: round((cnt / total_cases) * 100.0, 2) for a, cnt in optimal_action_counts.items()
    }
    no_action_opt_pct = optimal_pcts.get(RecoveryAction.NO_ACTION.value, 0.0)

    # Gaps
    mean_gap = int(np.mean(action_gaps))
    median_gap = int(np.median(action_gaps))
    p25_gap = int(np.percentile(action_gaps, 25))
    p75_gap = int(np.percentile(action_gaps, 75))

    expected_headroom = total_oracle_expected_net - total_baseline_expected_net
    expected_headroom_pct = (
        (expected_headroom / max(1, abs(total_baseline_expected_net))) * 100.0
    )

    def _summarize_subgroup(group_dict: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
        summary = {}
        for k, items in group_dict.items():
            cnt = len(items)
            if cnt > 0:
                mean_p = float(np.mean([x["opt_prob"] for x in items]))
                mean_amt = float(np.mean([x["amount_paise"] for x in items])) / 100.0
            else:
                mean_p = 0.0
                mean_amt = 0.0
            summary[k] = {
                "count": cnt,
                "mean_optimal_prob": mean_p,
                "mean_amount_inr": mean_amt,
            }
        return summary

    return CalibrationReport(
        total_cases=total_cases,
        total_revenue_at_risk_paise=total_risk_paise,
        mean_recovery_probabilities=mean_probs,
        p10_recovery_probabilities=p10_probs,
        p50_recovery_probabilities=p50_probs,
        p90_recovery_probabilities=p90_probs,
        optimal_action_counts=optimal_action_counts,
        optimal_action_percentages=optimal_pcts,
        no_action_optimal_pct=no_action_opt_pct,
        mean_action_value_gap_paise=mean_gap,
        median_action_value_gap_paise=median_gap,
        p25_action_value_gap_paise=p25_gap,
        p75_action_value_gap_paise=p75_gap,
        total_expected_oracle_net_paise=total_oracle_expected_net,
        total_expected_baseline_net_paise=total_baseline_expected_net,
        expected_headroom_paise=expected_headroom,
        expected_headroom_pct=round(expected_headroom_pct, 2),
        recovery_by_failure_type=_summarize_subgroup(ft_groups),
        recovery_by_customer_reliability=_summarize_subgroup(rel_groups),
        recovery_by_amount_bucket=_summarize_subgroup(amt_groups),
    )
