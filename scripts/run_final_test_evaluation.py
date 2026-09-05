"""
Final Benchmark Evaluation on Held-Out Test Set for RecoverAI Milestone 2.
Evaluates No Action, Rule Baseline, Logistic Decision Engine, GBM Decision Engine, and Oracle exactly ONCE.
Outputs reports/final_test_evaluation.json and reports/final_test_evaluation.md.
"""

import json
import sys
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth
from simulator.outcome_simulator import OutcomeSimulator
from simulator.policies.no_action import NoActionPolicy
from simulator.policies.rule_baseline import RuleBasedBaselinePolicy
from simulator.policies.oracle import OraclePolicy
from ml.dataset import load_split_dataset_bundle
from ml.models.bundle import create_multi_action_model, ACTION_ORDER
from ml.decision_engine import RecoveryDecisionEngine


def main():
    data_dir = Path("data/sim_v1")
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    print("[*] Training Champion Models on TRAIN split (7,000 cases)...")
    train_bundle = load_split_dataset_bundle(data_dir, split="train")

    logistic_multi = create_multi_action_model("logistic", calibrate=True, random_state=42).fit_all(train_bundle)
    logistic_engine = RecoveryDecisionEngine(model=logistic_multi)

    gbm_multi = create_multi_action_model("gbm", calibrate=True, random_state=42).fit_all(train_bundle)
    gbm_engine = RecoveryDecisionEngine(model=gbm_multi)

    print("[*] Loading Held-Out TEST split (1,500 cases)...")
    with open(data_dir / "test" / "observable_cases.json", "r", encoding="utf-8") as f:
        test_cases = [PaymentCase.model_validate(x) for x in json.load(f)]
    with open(data_dir / "test" / "hidden_ground_truth.json", "r", encoding="utf-8") as f:
        test_gt = {cid: CaseGroundTruth.model_validate(x) for cid, x in json.load(f).items()}

    total_revenue_at_risk_paise = sum(c.amount_paise for c in test_cases)
    n_cases = len(test_cases)

    no_action_policy = NoActionPolicy()
    rule_policy = RuleBasedBaselinePolicy()
    oracle_policy = OraclePolicy(ground_truth_map=test_gt)
    simulator = OutcomeSimulator(ground_truth_map=test_gt)

    def evaluate_policy_on_test(name, action_fn):
        gross_paise = 0
        cost_paise = 0
        net_paise = 0
        recovered_count = 0
        intervened_count = 0
        escalated_count = 0
        action_counts = Counter()

        subgroups = {
            "failure": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "method": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "retry": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "tier": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "sub": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
            "cust_succ": defaultdict(lambda: {"net": 0, "amt": 0, "n": 0, "rec": 0}),
        }

        for i, case in enumerate(test_cases):
            action = action_fn(case, i)
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

            sr = case.customer_historical_success_rate
            if sr < 0.60:
                sr_bin = "1. Low (< 60%)"
            elif sr < 0.80:
                sr_bin = "2. Medium (60-80%)"
            else:
                sr_bin = "3. High (> 80%)"

            for cat, key in [("failure", ft), ("method", pm), ("retry", rc), ("tier", tier), ("sub", sub), ("cust_succ", sr_bin)]:
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
            "subgroups": subgroups,
        }

    def evaluate_engine_batch_on_test(name, engine):
        dec_results = engine.evaluate_cases(test_cases)
        return evaluate_policy_on_test(name, lambda c, i: dec_results[i].selected_action)

    print("[*] Running Final Evaluations on TEST Split...")
    eval_no_action = evaluate_policy_on_test("No Action", lambda c, i: no_action_policy.predict(c))
    eval_rule = evaluate_policy_on_test("Rule Baseline", lambda c, i: rule_policy.predict(c))
    eval_logistic = evaluate_engine_batch_on_test("Logistic Decision Engine", logistic_engine)
    eval_gbm = evaluate_engine_batch_on_test("GBM Decision Engine", gbm_engine)
    eval_oracle = evaluate_policy_on_test("Oracle", lambda c, i: oracle_policy.predict(c))

    all_evals = [eval_no_action, eval_rule, eval_logistic, eval_gbm, eval_oracle]
    rule_net = eval_rule["net_paise"]
    oracle_net = eval_oracle["net_paise"]
    oracle_headroom_paise = oracle_net - rule_net

    # Format Console Output
    print("\n" + "=" * 120)
    print(f" FINAL BENCHMARK EVALUATION ON HELD-OUT TEST SPLIT ({n_cases:,} Cases | Revenue at Risk: INR {total_revenue_at_risk_paise/100:,.2f})")
    print("=" * 120)
    fmt = "{:<25} | {:>14} | {:>14} | {:>12} | {:>15} | {:>16} | {:>8} | {:>8} | {:>10}"
    print(fmt.format("Policy / Engine", "Net Rec (INR)", "Gross Rec (INR)", "Cost (INR)", "Delta vs Rule", "Regret vs Oracle", "Rec Rate", "Int Rate", "Headroom %"))
    print("-" * 120)

    for ev in all_evals:
        net_inr = ev["net_paise"] / 100.0
        gross_inr = ev["gross_paise"] / 100.0
        cost_inr = ev["cost_paise"] / 100.0
        delta_net_paise = ev["net_paise"] - rule_net
        delta_net_inr = delta_net_paise / 100.0
        pct_delta = (delta_net_paise / rule_net) * 100 if rule_net > 0 else 0.0
        regret_inr = (oracle_net - ev["net_paise"]) / 100.0
        rec_rate = ev["recovered_count"] / n_cases
        int_rate = ev["intervened_count"] / n_cases

        headroom_captured = (delta_net_paise / oracle_headroom_paise) * 100 if oracle_headroom_paise > 0 else 0.0

        if ev["name"] == "Rule Baseline":
            delta_str = "--"
            headroom_str = "--"
        elif ev["name"] == "Oracle":
            delta_str = f"+INR {delta_net_inr:,.2f} ({pct_delta:+.2f}%)"
            headroom_str = "100.0%"
        else:
            delta_str = f"+INR {delta_net_inr:,.2f} ({pct_delta:+.2f}%)" if delta_net_paise >= 0 else f"-INR {abs(delta_net_inr):,.2f} ({pct_delta:+.2f}%)"
            headroom_str = f"{headroom_captured:.1f}%"

        regret_str = f"INR {regret_inr:,.2f}" if ev["name"] != "Oracle" else "INR 0.00"

        print(fmt.format(
            ev["name"],
            f"INR {net_inr:,.2f}",
            f"INR {gross_inr:,.2f}",
            f"INR {cost_inr:,.2f}",
            delta_str,
            regret_str,
            f"{rec_rate:.1%}",
            f"{int_rate:.1%}",
            headroom_str,
        ))
    print("=" * 120)

    # Save JSON artifact
    json_results = {
        "split": "test",
        "num_cases": n_cases,
        "revenue_at_risk_paise": total_revenue_at_risk_paise,
        "revenue_at_risk_inr": total_revenue_at_risk_paise / 100.0,
        "policies": {},
    }

    for ev in all_evals:
        delta_net_paise = ev["net_paise"] - rule_net
        json_results["policies"][ev["name"]] = {
            "net_recovered_paise": ev["net_paise"],
            "net_recovered_inr": ev["net_paise"] / 100.0,
            "gross_recovered_paise": ev["gross_paise"],
            "gross_recovered_inr": ev["gross_paise"] / 100.0,
            "intervention_cost_paise": ev["cost_paise"],
            "intervention_cost_inr": ev["cost_paise"] / 100.0,
            "delta_vs_rule_baseline_paise": delta_net_paise,
            "delta_vs_rule_baseline_inr": delta_net_paise / 100.0,
            "delta_vs_rule_baseline_pct": (delta_net_paise / rule_net) * 100 if rule_net > 0 else 0.0,
            "regret_vs_oracle_paise": oracle_net - ev["net_paise"],
            "regret_vs_oracle_inr": (oracle_net - ev["net_paise"]) / 100.0,
            "recovery_rate": ev["recovered_count"] / n_cases,
            "intervention_rate": ev["intervened_count"] / n_cases,
            "escalation_rate": ev["escalated_count"] / n_cases,
            "action_counts": {act.value: ev["action_counts"][act] for act in ACTION_ORDER},
        }

    with open(reports_dir / "final_test_evaluation.json", "w", encoding="utf-8") as f:
        json.dump(json_results, f, indent=2)

    # Save Markdown artifact
    md_lines = [
        "# Final Benchmark Evaluation Report — RecoverAI (Held-Out Test Split)",
        "",
        f"- **Dataset**: `sim_v1` Held-Out Test Set ({n_cases:,} Cases, 300 Unseen Customers)",
        f"- **Total Revenue at Risk**: ₹{total_revenue_at_risk_paise/100:,.2f} ({total_revenue_at_risk_paise:,} paise)",
        f"- **Evaluation Framework**: Potential Outcomes under Common Random Numbers (Deterministic Realization)",
        "",
        "## 1. Primary Economic Benchmark Table",
        "",
        "| Policy / Model Engine | Net Recovery (INR) | Gross Recovery (INR) | Intervention Cost (INR) | Delta vs Rule Baseline | Regret vs Oracle | Recovery Rate | Intervention Rate | Oracle Headroom Captured |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for ev in all_evals:
        net_inr = ev["net_paise"] / 100.0
        gross_inr = ev["gross_paise"] / 100.0
        cost_inr = ev["cost_paise"] / 100.0
        delta_net_paise = ev["net_paise"] - rule_net
        delta_net_inr = delta_net_paise / 100.0
        pct_delta = (delta_net_paise / rule_net) * 100 if rule_net > 0 else 0.0
        regret_inr = (oracle_net - ev["net_paise"]) / 100.0
        rec_rate = ev["recovered_count"] / n_cases
        int_rate = ev["intervened_count"] / n_cases
        headroom_captured = (delta_net_paise / oracle_headroom_paise) * 100 if oracle_headroom_paise > 0 else 0.0

        if ev["name"] == "Rule Baseline":
            d_str = "--"
            h_str = "--"
        elif ev["name"] == "Oracle":
            d_str = f"+₹{delta_net_inr:,.2f} ({pct_delta:+.2f}%)"
            h_str = "100.0%"
        else:
            d_str = f"+₹{delta_net_inr:,.2f} ({pct_delta:+.2f}%)" if delta_net_paise >= 0 else f"-₹{abs(delta_net_inr):,.2f} ({pct_delta:+.2f}%)"
            h_str = f"{headroom_captured:.1f}%"

        r_str = f"₹{regret_inr:,.2f}" if ev["name"] != "Oracle" else "₹0.00"

        md_lines.append(
            f"| **{ev['name']}** | ₹{net_inr:,.2f} | ₹{gross_inr:,.2f} | ₹{cost_inr:,.2f} | {d_str} | {r_str} | {rec_rate:.1%} | {int_rate:.1%} | {h_str} |"
        )

    md_lines.extend([
        "",
        "## 2. Action Distributions",
        "",
        "| Policy / Engine | No Action | Retry | Payment Link | Reminder | Escalate |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for ev in all_evals:
        ac = ev["action_counts"]
        md_lines.append(
            f"| **{ev['name']}** | {ac[RecoveryAction.NO_ACTION]} ({ac[RecoveryAction.NO_ACTION]/n_cases:.1%}) | {ac[RecoveryAction.RETRY]} ({ac[RecoveryAction.RETRY]/n_cases:.1%}) | {ac[RecoveryAction.PAYMENT_LINK]} ({ac[RecoveryAction.PAYMENT_LINK]/n_cases:.1%}) | {ac[RecoveryAction.REMINDER]} ({ac[RecoveryAction.REMINDER]/n_cases:.1%}) | {ac[RecoveryAction.ESCALATE]} ({ac[RecoveryAction.ESCALATE]/n_cases:.1%}) |"
        )

    with open(reports_dir / "final_test_evaluation.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    print(f"\n[+] Saved reproducible test benchmark reports to:")
    print(f"    - {reports_dir / 'final_test_evaluation.json'}")
    print(f"    - {reports_dir / 'final_test_evaluation.md'}")


if __name__ == "__main__":
    main()
