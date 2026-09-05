"""
CLI Tool for RecoverAI Milestone 7: Scalable Performance & Stress Benchmarking.
Evaluates RecoverAI at scale (1K, 10K, 100K, 250K, 500K) with latency, throughput, memory,
and customer-clustered bootstrap uncertainty estimation.
Outputs reports/m7_scale_benchmark.json and reports/m7_scale_benchmark.md.
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from ml.evaluation.schemas import BenchmarkConfig
from ml.evaluation.workload import WORKLOAD_PROFILES
from ml.evaluation.harness import ScaleBenchmarkHarness, generate_markdown_report


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run RecoverAI Milestone 7 Scale & Stress Benchmark.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--profile",
        type=str,
        default="standard",
        choices=["smoke", "standard", "stress", "large", "full", "custom"],
        help="Workload preset (smoke=1k, standard=10k, stress=100k, large=250k, full=500k)",
    )
    parser.add_argument(
        "--cases",
        type=int,
        default=None,
        help="Explicit case count override",
    )
    parser.add_argument(
        "--customers",
        type=int,
        default=None,
        help="Explicit customer count override",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic workload generation and evaluation",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1024,
        help="Batch chunk size for vectorized inference",
    )
    parser.add_argument(
        "--bootstrap",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable/disable customer-clustered bootstrap uncertainty estimation",
    )
    parser.add_argument(
        "--bootstrap-reps",
        type=int,
        default=500,
        help="Number of bootstrap resamples (default: 500)",
    )
    parser.add_argument(
        "--compare-single-batch",
        action="store_true",
        default=False,
        help="Run single-case vs batch comparative benchmark",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports",
        help="Directory to save benchmark JSON and MD reports",
    )
    parser.add_argument(
        "--model-source",
        type=str,
        default="models/champion_recovery_model.pkl",
        help="Path to trained champion model artifact",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Determine cases and customers
    if args.cases is not None:
        num_cases = args.cases
        num_customers = args.customers if args.customers is not None else max(50, num_cases // 5)
        prof_name = "custom"
    else:
        prof_info = WORKLOAD_PROFILES.get(args.profile, WORKLOAD_PROFILES["standard"])
        num_cases = prof_info["cases"]
        num_customers = prof_info["customers"]
        prof_name = args.profile

    config = BenchmarkConfig(
        profile=prof_name,
        num_cases=num_cases,
        num_customers=num_customers,
        seed=args.seed,
        batch_size=args.batch_size,
        enable_bootstrap=args.bootstrap,
        bootstrap_reps=args.bootstrap_reps,
        model_source=args.model_source,
    )

    print("=" * 90)
    print(" RECOVERAI MILESTONE 7: SCALE & STRESS EVALUATION HARNESS")
    print("=" * 90)
    print(f"[*] Profile:           {config.profile.upper()}")
    print(f"[*] Workload:          {config.num_cases:,} cases | {config.num_customers:,} customers")
    print(f"[*] Batch Size:        {config.batch_size:,}")
    print(f"[*] Random Seed:       {config.seed} (CRN paired outcomes)")
    print(f"[*] Bootstrap CI:      {'Enabled (B=' + str(config.bootstrap_reps) + ')' if config.enable_bootstrap else 'Disabled'}")
    print(f"[*] Single vs Batch:   {'Enabled' if args.compare_single_batch else 'Disabled'}")
    print(f"[*] Model Artifact:    {config.model_source}")
    print("=" * 90)

    harness = ScaleBenchmarkHarness(config)
    print("\n[*] Executing benchmark harness pipeline...")
    report = harness.run_benchmark(compare_single_batch=args.compare_single_batch)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "m7_scale_benchmark.json"
    md_path = out_dir / "m7_scale_benchmark.md"

    with open(json_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(report.model_dump(), indent=2))

    md_content = generate_markdown_report(report)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print("\n" + "=" * 90)
    print(" BENCHMARK COMPLETED SUCCESSFULLY")
    print("=" * 90)
    perf = report.performance
    print(f"[*] Total Elapsed:     {perf['total_elapsed_ms']:,.2f} ms")
    print(f"[*] Overall Rate:      {perf['throughput_cases_per_sec']:,.1f} cases/sec")
    print(f"[*] Peak Memory:       {perf['memory']['peak_memory_mb']:.2f} MB ({perf['memory']['memory_per_case_kb']:.3f} KB/case)")
    print(f"\n[+] Saved machine-readable report: {json_path}")
    print(f"[+] Saved comprehensive report:    {md_path}")
    print("=" * 90)


if __name__ == "__main__":
    main()
