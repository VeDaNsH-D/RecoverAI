"""
CLI Script to evaluate recovery policies on a simulated dataset split.
Usage:
    python scripts/evaluate.py --data-dir data/sim_v1 --split test
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth
from simulator.outcome_simulator import OutcomeSimulator
from simulator.policies.base import BasePolicy
from simulator.policies.no_action import NoActionPolicy
from simulator.policies.rule_baseline import RuleBasedBaselinePolicy
from simulator.policies.oracle import OraclePolicy
from simulator.evaluator import EvaluationEngine, MultiPolicyComparison
from simulator.calibration import analyze_calibration


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate RecoverAI policies on dataset.")
    parser.add_argument("--data-dir", type=str, default="data/sim_v1", help="Dataset directory")
    parser.add_argument("--split", type=str, default="test", choices=["train", "val", "test"], help="Dataset split")
    parser.add_argument("--policies", type=str, default="no_action,rule_baseline,oracle", help="Comma-separated policy names")
    parser.add_argument("--output", type=str, default=None, help="Optional output JSON summary path")
    parser.add_argument("--calibrate", action="store_true", help="Run diagnostic simulator calibration analysis")
    return parser.parse_args()


def load_dataset(split_dir: Path):
    cases_file = split_dir / "observable_cases.json"
    gt_file = split_dir / "hidden_ground_truth.json"

    if not cases_file.exists() or not gt_file.exists():
        raise FileNotFoundError(
            f"Dataset files not found in {split_dir}. Please run scripts/generate_data.py first."
        )

    with open(cases_file, "r", encoding="utf-8") as f:
        cases_raw = json.load(f)
        cases = [PaymentCase.model_validate(item) for item in cases_raw]

    with open(gt_file, "r", encoding="utf-8") as f:
        gt_raw = json.load(f)
        gt_map = {cid: CaseGroundTruth.model_validate(item) for cid, item in gt_raw.items()}

    return cases, gt_map


def main():
    args = parse_args()
    data_dir = Path(args.data_dir)
    split_dir = data_dir / args.split

    print(f"[*] Loading '{args.split}' split from: {split_dir}...")
    cases, gt_map = load_dataset(split_dir)
    print(f"    Loaded {len(cases):,} observable cases and {len(gt_map):,} ground-truth records.")

    # Instantiate Simulator and Evaluator
    simulator = OutcomeSimulator(ground_truth_map=gt_map)
    evaluator = EvaluationEngine(simulator=simulator)

    # Policy Factory
    policy_names = [p.strip() for p in args.policies.split(",") if p.strip()]
    policies_to_run: List[BasePolicy] = []

    for p_name in policy_names:
        if p_name == "no_action":
            policies_to_run.append(NoActionPolicy())
        elif p_name in ("baseline", "rule_baseline"):
            policies_to_run.append(RuleBasedBaselinePolicy())
        elif p_name == "oracle":
            policies_to_run.append(OraclePolicy(ground_truth_map=gt_map))
        else:
            raise ValueError(f"Unknown policy name: '{p_name}'. Available: no_action, rule_baseline, oracle")

    print(f"[*] Running multi-policy evaluation across {len(policies_to_run)} policies...")
    comparison = evaluator.evaluate_policies(
        policies=policies_to_run,
        cases=cases,
        split_name=args.split,
        baseline_policy_name="rule_baseline",
    )

    # Print Formatted Report
    report = comparison.generate_console_report()
    print("\n" + report + "\n")

    if args.calibrate:
        print("[*] Generating Simulation Diagnostic Calibration Report...")
        cal_report = analyze_calibration(cases=cases, ground_truth_map=gt_map)
        print("\n" + cal_report.generate_console_report() + "\n")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(comparison.to_json_str(indent=2))
        print(f"[✓] Saved evaluation report to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
