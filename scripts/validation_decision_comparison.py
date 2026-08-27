"""
Validation Decision Comparison Script for RecoverAI Milestone 2.
Compares Rule Baseline vs Logistic Decision Engine vs GBM Decision Engine vs Oracle on the Validation Split.
"""

import json
import sys
from pathlib import Path
from collections import Counter, defaultdict

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import numpy as np

from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth
from simulator.outcome_simulator import OutcomeSimulator
from simulator.policies.rule_baseline import RuleBasedBaselinePolicy
from simulator.policies.oracle import OraclePolicy
from ml.dataset import load_split_dataset_bundle
from ml.models.bundle import create_multi_action_model, ACTION_ORDER
from ml.decision_engine import RecoveryDecisionEngine


def main():
    data_dir = Path("data/sim_v1")

    print("[*] Loading Train Split (7,000 cases)...")
    train_bundle = load_split_dataset_bundle(data_dir, split="train")

    print("[*] Loading Validation Split (1,500 cases)...")
    val_bundle = load_split_dataset_bundle(data_dir, split="val")

    with open(data_dir / "val" / "observable_cases.json", "r", encoding="utf-8") as f:
        val_cases = [PaymentCase.model_validate(x) for x in json.load(f)]
    with open(data_dir / "val" / "hidden_ground_truth.json", "r", encoding="utf-8") as f:
        val_gt = {cid: CaseGroundTruth.model_validate(x) for cid, x in json.load(f).items()}

    total_revenue_at_risk_paise = sum(c.amount_paise for c in val_cases)

    # Train Models
    print("[*] Fitting Logistic Regression multi-action model...")
    logistic_multi = create_multi_action_model("logistic", calibrate=True, random_state=42).fit_all(train_bundle)
    logistic_engine = RecoveryDecisionEngine(model=logistic_multi)

    print("[*] Fitting HistGradientBoosting (GBM) multi-action model...")
    gbm_multi = create_multi_action_model("gbm", calibrate=True, random_state=42).fit_all(train_bundle)
    gbm_engine = RecoveryDecisionEngine(model=gbm_multi)

    rule_policy = RuleBasedBaselinePolicy()
    oracle_policy = OraclePolicy(ground_truth_map=val_gt)
    simulator = OutcomeSimulator(ground_truth_map=val_gt)

    def evaluate_policy(name, action_fn, collects_engine_stats=False):
        gross_paise = 0
        cost_paise = 0
        net_paise = 0
        recovered_count = 0
        intervened_count = 0
        escalated_count = 0
        action_counts = Counter()
        decision_margins = []
        expected_nets = []

        subgroups = {
            "failure": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "method": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "retry": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "tier": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "sub": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
        }

        for case in val_cases:
            if collects_engine_stats:
                dec = action_fn(case)
                action = dec.selected_action
                decision_margins.append(dec.decision_margin_paise)
                expected_nets.append(dec.selected_expected_net_paise)
            else:
                action = action_fn(case)

            action_counts[action] += 1
            res = simulator.execute_action(case, action)

            gross_paise += res.recovered_amount_paise
            cost_paise += res.intervention_cost_paise
            net_paise += res.net_recovered_amount_paise

            if res.recovered:
                recovered_count += 1
            if action != RecoveryAction.NO_ACTION:
                intervened_count += 1
            if action == RecoveryAction.ESCALATE:
                escalated_count += 1

            # Subgroup buckets
            ft = case.failure_type.value
            pm = case.payment_method.value
            rc = f"retries_{min(case.retry_count, 3)}"
            sub = "subscription" if case.is_subscription else "one_off"
            amt = case.amount_paise
            if amt < 20000:
                tier = "1. Micro (< INR 200)"
            elif amt <= 100000:
                tier = "2. Low (INR 200 - 1k)"
            elif amt <= 500000:
                tier = "3. Mid (INR 1k - 5k)"
            else:
                tier = "4. High (> INR 5k)"

            for cat, key in [("failure", ft), ("method", pm), ("retry", rc), ("tier", tier), ("sub", sub)]:
                subgroups[cat][key]["net"] += res.net_recovered_amount_paise
                subgroups[cat][key]["amt"] += case.amount_paise
                subgroups[cat][key]["n"] += 1
                if res.recovered:
                    subgroups[cat][key]["rec"] += 1

        return {
            "name": name,
            "gross_paise": gross_paise,
            "cost_paise": cost_paise,
            "net_paise": net_paise,
            "recovered_count": recovered_count,
            "intervened_count": intervened_count,
            "escalated_count": escalated_count,
            "action_counts": action_counts,
            "avg_margin_paise": float(np.mean(decision_margins)) if decision_margins else 0.0,
            "avg_expected_net_paise": float(np.mean(expected_nets)) if expected_nets else 0.0,
            "subgroups": subgroups,
        }

    def evaluate_engine_batch(name, engine):
        dec_results = engine.evaluate_cases(val_cases)
        gross_paise = 0
        cost_paise = 0
        net_paise = 0
        recovered_count = 0
        intervened_count = 0
        escalated_count = 0
        action_counts = Counter()
        decision_margins = [d.decision_margin_paise for d in dec_results]
        expected_nets = [d.selected_expected_net_paise for d in dec_results]

        subgroups = {
            "failure": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "method": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "retry": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "tier": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "sub": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
        }

        for case, dec in zip(val_cases, dec_results):
            action = dec.selected_action
            action_counts[action] += 1
            res = simulator.execute_action(case, action)

            gross_paise += res.recovered_amount_paise
            cost_paise += res.intervention_cost_paise
            net_paise += res.net_recovered_amount_paise

            if res.recovered:
                recovered_count += 1
            if action != RecoveryAction.NO_ACTION:
                intervened_count += 1
            if action == RecoveryAction.ESCALATE:
                escalated_count += 1

            ft = case.failure_type.value
            pm = case.payment_method.value
            rc = f"retries_{min(case.retry_count, 3)}"
            sub = "subscription" if case.is_subscription else "one_off"
            amt = case.amount_paise
            if amt < 20000:
                tier = "1. Micro (< INR 200)"
            elif amt <= 100000:
                tier = "2. Low (INR 200 - 1k)"
            elif amt <= 500000:
                tier = "3. Mid (INR 1k - 5k)"
            else:
                tier = "4. High (> INR 5k)"

            for cat, key in [("failure", ft), ("method", pm), ("retry", rc), ("tier", tier), ("sub", sub)]:
                subgroups[cat][key]["net"] += res.net_recovered_amount_paise
                subgroups[cat][key]["amt"] += case.amount_paise
                subgroups[cat][key]["n"] += 1
                if res.recovered:
                    subgroups[cat][key]["rec"] += 1

        return {
            "name": name,
            "gross_paise": gross_paise,
            "cost_paise": cost_paise,
            "net_paise": net_paise,
            "recovered_count": recovered_count,
            "intervened_count": intervened_count,
            "escalated_count": escalated_count,
            "action_counts": action_counts,
            "avg_margin_paise": float(np.mean(decision_margins)) if decision_margins else 0.0,
            "avg_expected_net_paise": float(np.mean(expected_nets)) if expected_nets else 0.0,
            "subgroups": subgroups,
        }

    eval_rule = evaluate_policy("Rule Baseline", lambda c: rule_policy.predict(c))
    eval_logistic = evaluate_engine_batch("Logistic Decision Engine", logistic_engine)
    eval_gbm = evaluate_engine_batch("GBM Decision Engine", gbm_engine)
    eval_oracle = evaluate_policy("Oracle", lambda c: oracle_policy.predict(c))

    all_evals = [eval_rule, eval_logistic, eval_gbm, eval_oracle]
    rule_net = eval_rule["net_paise"]
    oracle_net = eval_oracle["net_paise"]

    print("\n" + "=" * 115)
    print(f" RECOVERAI VALIDATION DECISION COMPARISON (SPLIT: VAL -- {len(val_cases):,} Cases | Revenue at Risk: INR {total_revenue_at_risk_paise/100:,.2f})")
    print("=" * 115)
    header = "{:<25} | {:>14} | {:>14} | {:>12} | {:>15} | {:>16} | {:>8} | {:>8}"
    print(header.format("Policy / Engine", "Net Rec (INR)", "Gross Rec (INR)", "Cost (INR)", "Delta vs Rule", "Regret vs Oracle", "Rec Rate", "Int Rate"))
    print("-" * 115)

    for ev in all_evals:
        net_inr = ev["net_paise"] / 100.0
        gross_inr = ev["gross_paise"] / 100.0
        cost_inr = ev["cost_paise"] / 100.0
        delta_net_paise = ev["net_paise"] - rule_net
        delta_net_inr = delta_net_paise / 100.0
        pct_delta = (delta_net_paise / rule_net) * 100 if rule_net > 0 else 0.0
        regret_inr = (oracle_net - ev["net_paise"]) / 100.0
        rec_rate = ev["recovered_count"] / len(val_cases)
        int_rate = ev["intervened_count"] / len(val_cases)

        if ev["name"] == "Rule Baseline":
            delta_str = "--"
        else:
            delta_str = f"+INR {delta_net_inr:,.2f} ({pct_delta:+.2f}%)" if delta_net_paise >= 0 else f"-INR {abs(delta_net_inr):,.2f} ({pct_delta:+.2f}%)"

        regret_str = f"INR {regret_inr:,.2f}" if ev["name"] != "Oracle" else "INR 0.00"

        print(header.format(
            ev["name"],
            f"INR {net_inr:,.2f}",
            f"INR {gross_inr:,.2f}",
            f"INR {cost_inr:,.2f}",
            delta_str,
            regret_str,
            f"{rec_rate:.1%}",
            f"{int_rate:.1%}",
        ))

    print("=" * 115)

    print("\nACTION DISTRIBUTIONS:")
    for ev in all_evals:
        ac = ev["action_counts"]
        parts = [f"{act.value}: {ac[act]:>4} ({ac[act]/len(val_cases):.1%})" for act in ACTION_ORDER]
        print(f"  {ev['name']:<25} -> " + " | ".join(parts))

    print("\nDECISION ENGINE INTERNAL ECONOMICS:")
    print(f"  Logistic Decision Engine: Avg Expected Net = INR {eval_logistic['avg_expected_net_paise']/100:,.2f} | Avg Decision Margin = INR {eval_logistic['avg_margin_paise']/100:,.2f}")
    print(f"  GBM Decision Engine     : Avg Expected Net = INR {eval_gbm['avg_expected_net_paise']/100:,.2f} | Avg Decision Margin = INR {eval_gbm['avg_margin_paise']/100:,.2f}")

    print("\nSUBGROUP PERFORMANCE BREAKDOWN (Net Recovery in INR):")
    categories = [
        ("Failure Type", "failure"),
        ("Transaction Amount Tier", "tier"),
        ("Payment Method", "method"),
        ("Retry Count", "retry"),
        ("Subscription Status", "sub"),
    ]

    for cat_label, cat_key in categories:
        print(f"\n--- {cat_label.upper()} ---")
        keys = sorted(eval_rule["subgroups"][cat_key].keys())
        sub_hdr = "{:<26} | {:>14} | {:>14} | {:>14} | {:>14} | {:>16}"
        print(sub_hdr.format("Subgroup", "Rule Net", "Logistic Net", "GBM Net", "Oracle Net", "Logistic Uplift"))
        print("-" * 105)
        for k in keys:
            r_net = eval_rule["subgroups"][cat_key][k]["net"] / 100.0
            l_net = eval_logistic["subgroups"][cat_key][k]["net"] / 100.0
            g_net = eval_gbm["subgroups"][cat_key][k]["net"] / 100.0
            o_net = eval_oracle["subgroups"][cat_key][k]["net"] / 100.0
            up = l_net - r_net
            up_pct = (up / r_net) * 100 if r_net > 0 else 0.0
            up_str = f"+INR {up:,.2f} ({up_pct:+.1f}%)" if up >= 0 else f"-INR {abs(up):,.2f} ({up_pct:+.1f}%)"
            print(sub_hdr.format(k, f"INR {r_net:,.2f}", f"INR {l_net:,.2f}", f"INR {g_net:,.2f}", f"INR {o_net:,.2f}", up_str))


if __name__ == "__main__":
    main()
