"""
Performance and memory profiling utility for RecoverAI Milestone 7: Scale Evaluation & Optimization.
Measures stage timings, per-case latency distributions, tracemalloc peak memory, and single vs. batch inference.
"""

from typing import Dict, List, Optional
import time
import tracemalloc
import numpy as np

from ml.evaluation.schemas import (
    StageTiming,
    LatencyPercentiles,
    MemoryMetrics,
    InferenceComparisonMetrics,
)


class BenchmarkTimer:
    """
    High-resolution stage timer and throughput recorder.
    """

    def __init__(self, num_cases: int):
        self.num_cases = num_cases
        self.stage_timings: Dict[str, StageTiming] = {}
        self._current_stage: Optional[str] = None
        self._stage_start_ns: Optional[int] = None

    def start_stage(self, stage_name: str) -> None:
        """Starts timing a specific pipeline stage."""
        self._current_stage = stage_name
        self._stage_start_ns = time.perf_counter_ns()

    def end_stage(self, stage_name: Optional[str] = None) -> StageTiming:
        """Stops timing the current stage and records elapsed milliseconds and throughput."""
        end_ns = time.perf_counter_ns()
        st_name = stage_name or self._current_stage or "unknown_stage"
        start_ns = self._stage_start_ns if self._stage_start_ns is not None else end_ns

        elapsed_ms = (end_ns - start_ns) / 1_000_000.0
        elapsed_sec = max(1e-9, elapsed_ms / 1000.0)
        throughput = self.num_cases / elapsed_sec
        mean_ms_per_case = elapsed_ms / max(1, self.num_cases)

        timing = StageTiming(
            stage_name=st_name,
            elapsed_ms=round(elapsed_ms, 2),
            throughput_cases_per_sec=round(throughput, 1),
            mean_ms_per_case=round(mean_ms_per_case, 5),
        )
        self.stage_timings[st_name] = timing
        self._current_stage = None
        self._stage_start_ns = None
        return timing


class MemoryProfiler:
    """
    Tracks baseline and peak process memory using standard-library tracemalloc.
    """

    def __init__(self, num_cases: int):
        self.num_cases = num_cases
        self._baseline_bytes: int = 0
        self._is_active: bool = False

    def start(self) -> None:
        """Starts memory tracking."""
        tracemalloc.start()
        current, peak = tracemalloc.get_traced_memory()
        self._baseline_bytes = current
        self._is_active = True

    def stop(self) -> MemoryMetrics:
        """Stops memory tracking and computes peak memory metrics."""
        if not self._is_active:
            return MemoryMetrics(
                baseline_memory_mb=0.0,
                peak_memory_mb=0.0,
                incremental_memory_mb=0.0,
                memory_per_case_kb=0.0,
            )

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self._is_active = False

        baseline_mb = self._baseline_bytes / (1024.0 * 1024.0)
        peak_mb = peak / (1024.0 * 1024.0)
        incremental_mb = max(0.0, peak - self._baseline_bytes) / (1024.0 * 1024.0)
        kb_per_case = (max(0.0, peak - self._baseline_bytes) / 1024.0) / max(1, self.num_cases)

        return MemoryMetrics(
            baseline_memory_mb=round(baseline_mb, 2),
            peak_memory_mb=round(peak_mb, 2),
            incremental_memory_mb=round(incremental_mb, 2),
            memory_per_case_kb=round(kb_per_case, 3),
        )


def calculate_latency_percentiles(latencies_ms: np.ndarray) -> LatencyPercentiles:
    """Computes P50, P90, P95, P99, and Mean per-case latency."""
    if len(latencies_ms) == 0:
        return LatencyPercentiles(p50_ms=0.0, p90_ms=0.0, p95_ms=0.0, p99_ms=0.0, mean_ms=0.0)

    return LatencyPercentiles(
        p50_ms=round(float(np.percentile(latencies_ms, 50)), 4),
        p90_ms=round(float(np.percentile(latencies_ms, 90)), 4),
        p95_ms=round(float(np.percentile(latencies_ms, 95)), 4),
        p99_ms=round(float(np.percentile(latencies_ms, 99)), 4),
        mean_ms=round(float(np.mean(latencies_ms)), 4),
    )


def benchmark_single_vs_batch_inference(
    decision_engine,
    cases: list,
    sample_size: int = 500,
) -> InferenceComparisonMetrics:
    """
    Compares single-case inference loop against vectorized batch inference on a representative sample.
    """
    bench_cases = cases[:sample_size] if len(cases) > sample_size else cases
    n = len(bench_cases)

    # 1. Single-case inference loop
    start_single = time.perf_counter_ns()
    single_actions = []
    for c in bench_cases:
        act = decision_engine.select_action(c)
        single_actions.append(act)
    elapsed_single_ms = (time.perf_counter_ns() - start_single) / 1_000_000.0

    single_throughput = n / max(1e-9, elapsed_single_ms / 1000.0)
    single_latency = elapsed_single_ms / max(1, n)

    # 2. Vectorized batch inference
    start_batch = time.perf_counter_ns()
    batch_actions = decision_engine.select_actions_fast(bench_cases)
    elapsed_batch_ms = (time.perf_counter_ns() - start_batch) / 1_000_000.0

    batch_throughput = n / max(1e-9, elapsed_batch_ms / 1000.0)
    batch_latency = elapsed_batch_ms / max(1, n)

    # Assert exact action equivalence
    assert single_actions == batch_actions, "Decision mismatch detected during single vs batch inference comparison!"

    speedup = single_latency / max(1e-9, batch_latency)

    return InferenceComparisonMetrics(
        single_total_ms=round(elapsed_single_ms, 2),
        single_throughput_cases_per_sec=round(single_throughput, 1),
        single_latency_ms_per_case=round(single_latency, 4),
        batch_total_ms=round(elapsed_batch_ms, 2),
        batch_throughput_cases_per_sec=round(batch_throughput, 1),
        batch_latency_ms_per_case=round(batch_latency, 4),
        speedup_factor=round(speedup, 2),
    )
