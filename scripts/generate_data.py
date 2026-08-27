"""
CLI Script to generate synthetic revenue recovery datasets with customer-level splits.
Usage:
    python scripts/generate_data.py --seed 42 --customers 2000 --cases 10000 --output-dir data/sim_v1
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List
import numpy as np

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.config import (
    DEFAULT_CUSTOMER_COUNT,
    DEFAULT_CASE_COUNT,
    DEFAULT_RANDOM_SEED,
    DEFAULT_TRAIN_RATIO,
    DEFAULT_VAL_RATIO,
    DEFAULT_TEST_RATIO,
)
from simulator.generators.customer_generator import generate_customers
from simulator.generators.case_generator import generate_cases
from simulator.generators.ground_truth_generator import generate_ground_truth
from simulator.schemas.customer import CustomerProfile
from simulator.schemas.case import PaymentCase
from simulator.schemas.ground_truth import CaseGroundTruth


def parse_args():
    parser = argparse.ArgumentParser(description="Generate synthetic revenue recovery dataset.")
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED, help="Random seed (default: 42)")
    parser.add_argument("--customers", type=int, default=DEFAULT_CUSTOMER_COUNT, help="Customer count (default: 2000)")
    parser.add_argument("--cases", type=int, default=DEFAULT_CASE_COUNT, help="Total case count (default: 10000)")
    parser.add_argument("--output-dir", type=str, default="data/sim_v1", help="Output directory (default: data/sim_v1)")
    parser.add_argument("--train-ratio", type=float, default=DEFAULT_TRAIN_RATIO, help="Train split ratio (default: 0.70)")
    parser.add_argument("--val-ratio", type=float, default=DEFAULT_VAL_RATIO, help="Val split ratio (default: 0.15)")
    parser.add_argument("--test-ratio", type=float, default=DEFAULT_TEST_RATIO, help="Test split ratio (default: 0.15)")
    return parser.parse_args()


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main():
    args = parse_args()
    print(f"[*] Starting RecoverAI Dataset Generation...")
    print(f"    Seed: {args.seed}")
    print(f"    Customers: {args.customers:,}")
    print(f"    Cases: {args.cases:,}")
    print(f"    Output Directory: {args.output_dir}")
    print(f"    Split Ratios: train={args.train_ratio}, val={args.val_ratio}, test={args.test_ratio}")

    rng = np.random.default_rng(args.seed)

    # 1. Generate All Customers
    print(f"[*] Generating {args.customers:,} customer profiles...")
    customers = generate_customers(count=args.customers, seed=args.seed)
    
    # 2. Partition Customers into Splits (Guarantees zero customer identity leakage)
    cust_indices = np.arange(len(customers))
    rng.shuffle(cust_indices)

    train_end = int(args.train_ratio * len(customers))
    val_end = train_end + int(args.val_ratio * len(customers))

    train_custs = [customers[i] for i in cust_indices[:train_end]]
    val_custs = [customers[i] for i in cust_indices[train_end:val_end]]
    test_custs = [customers[i] for i in cust_indices[val_end:]]

    # Target case counts per split
    train_cases_count = int(args.cases * args.train_ratio)
    val_cases_count = int(args.cases * args.val_ratio)
    test_cases_count = args.cases - train_cases_count - val_cases_count

    splits_data = [
        ("train", train_custs, train_cases_count, args.seed + 101),
        ("val", val_custs, val_cases_count, args.seed + 202),
        ("test", test_custs, test_cases_count, args.seed + 303),
    ]

    out_dir = Path(args.output_dir)
    metadata_splits = {}

    for split_name, split_customers, split_case_count, split_seed in splits_data:
        print(f"[*] Generating '{split_name}' split: {len(split_customers):,} customers, {split_case_count:,} cases...")
        
        # Observable Cases
        cases = generate_cases(split_customers, total_cases=split_case_count, seed=split_seed)
        
        # Hidden Ground Truth
        cust_map = {c.customer_id: c for c in split_customers}
        ground_truth_map = generate_ground_truth(cases, cust_map, seed=split_seed + 1000)

        # Save Observable features
        observable_path = out_dir / split_name / "observable_cases.json"
        save_json(observable_path, [c.model_dump() for c in cases])

        # Save Hidden Ground Truth
        gt_path = out_dir / split_name / "hidden_ground_truth.json"
        save_json(gt_path, {cid: gt.model_dump() for cid, gt in ground_truth_map.items()})

        total_risk_paise = sum(c.amount_paise for c in cases)
        metadata_splits[split_name] = {
            "customers_count": len(split_customers),
            "cases_count": len(cases),
            "total_revenue_at_risk_paise": total_risk_paise,
            "total_revenue_at_risk_inr": total_risk_paise / 100.0,
            "observable_cases_file": str(observable_path.as_posix()),
            "hidden_ground_truth_file": str(gt_path.as_posix()),
        }

    # Save Customer profiles catalog
    save_json(out_dir / "customers.json", [c.model_dump() for c in customers])

    # Save Master Metadata
    metadata = {
        "dataset_name": "RecoverAI Synthetic Benchmark v1",
        "random_seed": args.seed,
        "total_customers": len(customers),
        "total_cases": args.cases,
        "splits": metadata_splits,
    }
    save_json(out_dir / "metadata.json", metadata)

    print("\n" + "=" * 70)
    print(" DATASET GENERATION COMPLETE")
    print("=" * 70)
    for s_name, s_meta in metadata_splits.items():
        print(f" Split [{s_name.upper():<5}]: {s_meta['customers_count']:,} customers | {s_meta['cases_count']:,} cases | Risk: INR {s_meta['total_revenue_at_risk_inr']:,.2f}")
    print(f" Artifacts saved to: {out_dir.resolve()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
