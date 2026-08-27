"""
Diagnostic script to investigate the decision gap between Oracle and ML decision engines.
Examines action distributions, per-action probability calibration errors, EV ranking quality,
confusion matrices, and regret breakdown on the Validation split.
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
from simulator.policies.rule_baseline import RuleBasedBaselinePolicy
from simulator.policies.oracle import OraclePolicy
from ml.dataset import load_split_dataset_bundle
from ml.models.bundle import create_multi_action_model, ACTION_ORDER
from ml.decision_engine import RecoveryDecisionEngine


def main():
    data_dir = Path("data/sim_v1")

    print("[*] Loading Train Split for fitting models...")
    train_bundle = load_split_dataset_bundle(data_dir, split="train")

    print("[*] Loading Validation Split for offline diagnosis...")
    with open(data_dir / "val" / "observable_cases.json", "r", encoding="utf-8") as f:
        val_cases = [PaymentCase.model_validate(x) for x in json.load(f)]
    with open(data_dir / "val" / "hidden_ground_truth.json", "r", encoding="utf-8") as f:
        val_gt = {cid: CaseGroundTruth.model_validate(x) for cid, x in json.load(f).items()}

    # 1. Train models on Train
    print("[*] Fitting Logistic Regression multi-action model...")
    logistic_multi = create_multi_action_model("logistic", calibrate=True, random_state=42).fit_all(train_bundle)
    logistic_engine = RecoveryDecisionEngine(model=logistic_multi)

    print("[*] Fitting GBM multi-action model...")
    gbm_multi = create_multi_action_model("gbm", calibrate=True, random_state=42).fit_all(train_bundle)
    gbm_engine = RecoveryDecisionEngine(model=gbm_multi)

    oracle_policy = OraclePolicy(ground_truth_map=val_gt)
    rule_policy = RuleBasedBaselinePolicy()
    simulator = OutcomeSimulator(ground_truth_map=val_gt)

    # 2. Evaluate batch decisions
    logistic_decisions = logistic_engine.evaluate_cases(val_cases)
    gbm_decisions = gbm_engine.evaluate_cases(val_cases)

    # 3. Analyze case by case
    n_cases = len(val_cases)

    oracle_actions = []
    logistic_actions = []
    gbm_actions = []
    rule_actions = []

    # Confusion matrices: [True/Oracle, Predicted/ML]
    confusion_logistic = defaultdict(Counter)
    confusion_gbm = defaultdict(Counter)

    # Probability errors per action
    prob_errors_logistic = {act: [] for act in ACTION_ORDER}
    prob_errors_gbm = {act: [] for act in ACTION_ORDER}
    true_probs_all = {act: [] for act in ACTION_ORDER}
    pred_probs_logistic = {act: [] for act in ACTION_ORDER}
    pred_probs_gbm = {act: [] for act in ACTION_ORDER}

    # Regrets
    regrets_logistic = []
    regrets_gbm = []
    regrets_rule = []

    # Ranks of true best action
    rank_logistic = []
    rank_gbm = []

    # Cases where Oracle selects NO_ACTION
    oracle_no_action_cases = []

    # Regret by subgroups
    regret_by_failure = defaultdict(list)
    regret_by_retry = defaultdict(list)
    regret_by_sub = defaultdict(list)
    regret_by_tier = defaultdict(list)
    regret_by_cust_succ = defaultdict(list)

    for i, case in enumerate(val_cases):
        gt = val_gt[case.case_id]
        log_dec = logistic_decisions[i]
        gbm_dec = gbm_decisions[i]

        act_oracle = oracle_policy.predict(case)
        act_logistic = log_dec.selected_action
        act_gbm = gbm_dec.selected_action
        act_rule = rule_policy.predict(case)

        oracle_actions.append(act_oracle)
        logistic_actions.append(act_logistic)
        gbm_actions.append(act_gbm)
        rule_actions.append(act_rule)

        confusion_logistic[act_oracle][act_logistic] += 1
        confusion_gbm[act_oracle][act_gbm] += 1

        # Realized payoffs under Common Random Numbers
        res_oracle = simulator.execute_action(case, act_oracle)
        res_logistic = simulator.execute_action(case, act_logistic)
        res_gbm = simulator.execute_action(case, act_gbm)
        res_rule = simulator.execute_action(case, act_rule)

        reg_log = (res_oracle.net_recovered_amount_paise - res_logistic.net_recovered_amount_paise) / 100.0
        reg_gbm = (res_oracle.net_recovered_amount_paise - res_gbm.net_recovered_amount_paise) / 100.0
        reg_rule = (res_oracle.net_recovered_amount_paise - res_rule.net_recovered_amount_paise) / 100.0

        regrets_logistic.append(reg_log)
        regrets_gbm.append(reg_gbm)
        regrets_rule.append(reg_rule)

        # Track probability errors
        for act in ACTION_ORDER:
            p_true = gt.recovery_probabilities[act]
            p_log = log_dec.action_values[act].predicted_probability
            p_gbm = gbm_dec.action_values[act].predicted_probability

            true_probs_all[act].append(p_true)
            pred_probs_logistic[act].append(p_log)
            pred_probs_gbm[act].append(p_gbm)

            prob_errors_logistic[act].append(p_log - p_true)
            prob_errors_gbm[act].append(p_gbm - p_true)

        # Expected Value Ranking Quality
        # True expected nets from ground truth
        true_expected_nets = {
            act: int(np.floor(gt.recovery_probabilities[act] * case.amount_paise)) - ACTION_COSTS_PAISE[act]
            for act in ACTION_ORDER
        }
        # True best action by expected net
        true_best_act = max(true_expected_nets.keys(), key=lambda a: true_expected_nets[a])
        
        # Rank in Logistic model's expected net values
        sorted_log_acts = sorted(ACTION_ORDER, key=lambda a: -log_dec.action_values[a].expected_net_paise)
        rank_logistic.append(sorted_log_acts.index(true_best_act) + 1)

        sorted_gbm_acts = sorted(ACTION_ORDER, key=lambda a: -gbm_dec.action_values[a].expected_net_paise)
        rank_gbm.append(sorted_gbm_acts.index(true_best_act) + 1)

        # Subgroup tracking for Logistic regret
        ft = case.failure_type.value
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

        regret_by_failure[ft].append(reg_log)
        regret_by_retry[rc].append(reg_log)
        regret_by_sub[sub].append(reg_log)
        regret_by_tier[tier].append(reg_log)
        regret_by_cust_succ[sr_bin].append(reg_log)

        # Oracle NO_ACTION cases inspection
        if act_oracle == RecoveryAction.NO_ACTION:
            oracle_no_action_cases.append({
                "case_id": case.case_id,
                "amount_inr": case.amount_paise / 100.0,
                "failure_type": case.failure_type.value,
                "retry_count": case.retry_count,
                "is_subscription": case.is_subscription,
                "cust_success_rate": case.customer_historical_success_rate,
                "oracle_action": act_oracle.value,
                "logistic_action": act_logistic.value,
                "gbm_action": act_gbm.value,
                "rule_action": act_rule.value,
                "regret_logistic_inr": reg_log,
                "p_true_no_action": gt.recovery_probabilities[RecoveryAction.NO_ACTION],
                "p_true_retry": gt.recovery_probabilities[RecoveryAction.RETRY],
                "p_true_link": gt.recovery_probabilities[RecoveryAction.PAYMENT_LINK],
                "p_true_reminder": gt.recovery_probabilities[RecoveryAction.REMINDER],
                "p_true_escalate": gt.recovery_probabilities[RecoveryAction.ESCALATE],
                "p_log_no_action": log_dec.action_values[RecoveryAction.NO_ACTION].predicted_probability,
                "p_log_retry": log_dec.action_values[RecoveryAction.RETRY].predicted_probability,
                "p_log_link": log_dec.action_values[RecoveryAction.PAYMENT_LINK].predicted_probability,
                "p_log_reminder": log_dec.action_values[RecoveryAction.REMINDER].predicted_probability,
                "p_log_escalate": log_dec.action_values[RecoveryAction.ESCALATE].predicted_probability,
                "ev_true_no_action": true_expected_nets[RecoveryAction.NO_ACTION] / 100.0,
                "ev_true_best": true_expected_nets[true_best_act] / 100.0,
                "ev_log_selected": log_dec.selected_expected_net_paise / 100.0,
                "ev_log_no_action": log_dec.action_values[RecoveryAction.NO_ACTION].expected_net_paise / 100.0,
            })

    # Print Full Diagnostic Report
    print("\n" + "=" * 105)
    print(f" RECOVERAI DECISION GAP DIAGNOSTIC REPORT (VALIDATION SPLIT -- {n_cases:,} Cases)")
    print("=" * 105)

    print("\n[A] ACTION DISTRIBUTIONS:")
    for name, acts in [("Oracle", oracle_actions), ("Logistic Decision Engine", logistic_actions), ("GBM Decision Engine", gbm_actions), ("Rule Baseline", rule_actions)]:
        c = Counter(acts)
        parts = [f"{act.value}: {c[act]:>4} ({c[act]/n_cases:.1%})" for act in ACTION_ORDER]
        print(f"  {name:<26} -> " + " | ".join(parts))

    print(f"\n[B] NO_ACTION SELECTION FREQUENCY:")
    print(f"  Oracle selected NO_ACTION   : {oracle_actions.count(RecoveryAction.NO_ACTION):>4} / {n_cases} ({oracle_actions.count(RecoveryAction.NO_ACTION)/n_cases:.1%})")
    print(f"  Logistic selected NO_ACTION : {logistic_actions.count(RecoveryAction.NO_ACTION):>4} / {n_cases} ({logistic_actions.count(RecoveryAction.NO_ACTION)/n_cases:.1%})")
    print(f"  GBM selected NO_ACTION      : {gbm_actions.count(RecoveryAction.NO_ACTION):>4} / {n_cases} ({gbm_actions.count(RecoveryAction.NO_ACTION)/n_cases:.1%})")
    print(f"  Rule Baseline NO_ACTION     : {rule_actions.count(RecoveryAction.NO_ACTION):>4} / {n_cases} ({rule_actions.count(RecoveryAction.NO_ACTION)/n_cases:.1%})")

    print("\n[C] ACTION CONFUSION MATRIX (Rows: Oracle Action, Columns: Logistic ML Action):")
    conf_header = "{:<16} | " + " | ".join(f"{act.value:>12}" for act in ACTION_ORDER) + " | Total"
    print(conf_header.format("Oracle Action"))
    print("-" * 105)
    for act_true in ACTION_ORDER:
        row = [confusion_logistic[act_true][act_pred] for act_pred in ACTION_ORDER]
        total_true = sum(row)
        row_str = " | ".join(f"{val:>12}" for val in row)
        print(f"{act_true.value:<16} | {row_str} | {total_true:>5}")

    print("\n[D] PROBABILITY ESTIMATION ERROR ANALYSIS (Predicted P_hat vs True Simulator Probability P_true):")
    p_header = "{:<16} | {:>12} | {:>12} | {:>10} | {:>10} | {:>10}"
    print(p_header.format("Action", "Mean P_true", "Mean P_log", "Bias", "MAE", "RMSE"))
    print("-" * 85)
    for act in ACTION_ORDER:
        true_arr = np.array(true_probs_all[act])
        pred_arr = np.array(pred_probs_logistic[act])
        err_arr = pred_arr - true_arr
        bias = float(np.mean(err_arr))
        mae = float(np.mean(np.abs(err_arr)))
        rmse = float(np.sqrt(np.mean(err_arr**2)))
        print(p_header.format(
            act.value,
            f"{np.mean(true_arr):.4f}",
            f"{np.mean(pred_arr):.4f}",
            f"{bias:+.4f}",
            f"{mae:.4f}",
            f"{rmse:.4f}",
        ))

    print("\n[E] EXPECTED-VALUE RANKING QUALITY (Where does ML rank the True Best Action?):")
    rank_counts_log = Counter(rank_logistic)
    for rank in sorted(rank_counts_log.keys()):
        cnt = rank_counts_log[rank]
        print(f"  Rank #{rank}: {cnt:>4} cases ({cnt/n_cases:.1%})")
    print(f"  Top-1 Match Rate: {rank_counts_log[1]/n_cases:.1%}")
    print(f"  Top-2 Match Rate: {(rank_counts_log[1] + rank_counts_log[2])/n_cases:.1%}")

    print("\n[F] REGRET DISTRIBUTION (Realized Regret in INR vs Oracle):")
    arr_reg = np.array(regrets_logistic)
    print(f"  Mean Regret   : INR {np.mean(arr_reg):,.2f}")
    print(f"  Median (P50)  : INR {np.median(arr_reg):,.2f}")
    print(f"  P75 Regret    : INR {np.percentile(arr_reg, 75):,.2f}")
    print(f"  P90 Regret    : INR {np.percentile(arr_reg, 90):,.2f}")
    print(f"  P95 Regret    : INR {np.percentile(arr_arr := arr_reg, 95):,.2f}")
    print(f"  Max Regret    : INR {np.max(arr_reg):,.2f}")
    print(f"  Zero Regret % : {np.mean(arr_reg == 0):.1%} of cases had zero regret")

    print("\n[G] DETAILED ANALYSIS OF ORACLE NO_ACTION CASES (172 Cases):")
    print(f"  Total Oracle NO_ACTION cases: {len(oracle_no_action_cases)}")
    # What did Logistic select for these 172 cases?
    log_actions_for_no_action = Counter(c["logistic_action"] for c in oracle_no_action_cases)
    for act_name, count in log_actions_for_no_action.most_common():
        print(f"    ML selected '{act_name}': {count:>3} cases ({count/len(oracle_no_action_cases):.1%})")

    # Why did Oracle select NO_ACTION?
    # In Oracle, NO_ACTION is chosen when either all other actions have lower expected net, or true unrecoverability is present
    avg_p_true_link_in_no_act = np.mean([c["p_true_link"] for c in oracle_no_action_cases])
    avg_p_log_link_in_no_act = np.mean([c["p_log_link"] for c in oracle_no_action_cases])
    avg_amt_in_no_act = np.mean([c["amount_inr"] for c in oracle_no_action_cases])
    avg_reg_in_no_act = np.mean([c["regret_logistic_inr"] for c in oracle_no_action_cases])

    print(f"    Avg Transaction Value in Oracle NO_ACTION cases: INR {avg_amt_in_no_act:,.2f}")
    print(f"    Avg True Link Prob in Oracle NO_ACTION cases   : {avg_p_true_link_in_no_act:.2%}")
    print(f"    Avg ML Pred Link Prob in Oracle NO_ACTION cases: {avg_p_log_link_in_no_act:.2%}")
    print(f"    Avg Realized Regret in Oracle NO_ACTION cases  : INR {avg_reg_in_no_act:,.2f}")

    print("\n[H] REGRET BREAKDOWN BY SUBGROUPS (Mean Regret in INR):")
    for grp_name, grp_dict in [("Failure Type", regret_by_failure), ("Retry Count", regret_by_retry), ("Amount Tier", regret_by_tier), ("Subscription", regret_by_sub), ("Customer Success Rate", regret_by_cust_succ)]:
        print(f"\n  -- {grp_name} --")
        for k in sorted(grp_dict.keys()):
            vals = grp_dict[k]
            print(f"    {k:<24}: Mean Regret = INR {np.mean(vals):>8,.2f} | Total Cases = {len(vals):>4} | Total Regret = INR {np.sum(vals):>10,.2f}")


if __name__ == "__main__":
    main()
