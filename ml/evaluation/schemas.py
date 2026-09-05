"""
Pydantic schemas and data contracts for RecoverAI Milestone 7: Scale Evaluation & Optimization.
Strictly maintains integer paise financial quantities and robust reproducibility metadata.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import RecoveryAction, ACTION_COSTS_PAISE


class BenchmarkConfig(BaseModel):
    """Configuration contract for scale and stress evaluation runs."""
    model_config = ConfigDict(frozen=True)

    profile: str = Field(default="standard", description="Workload profile name: smoke, standard, stress, large, full")
    num_cases: int = Field(ge=1, description="Total number of payment cases to evaluate")
    num_customers: int = Field(ge=1, description="Total number of distinct customer profiles")
    seed: int = Field(default=42, description="Random seed for deterministic workload generation and evaluation")
    batch_size: int = Field(default=1024, ge=1, description="Batch chunk size for vectorized inference")
    enable_bootstrap: bool = Field(default=True, description="Whether to compute customer-clustered bootstrap CIs")
    bootstrap_reps: int = Field(default=500, ge=10, description="Number of bootstrap resamples (default: 500)")
    confidence_level: float = Field(default=0.95, ge=0.5, le=0.999, description="Confidence interval coverage (default: 0.95)")
    model_source: str = Field(default="models/champion_recovery_model.pkl", description="Path to model artifact or 'train_on_split'")


class LatencyPercentiles(BaseModel):
    """Per-case decision latency distribution percentiles in milliseconds."""
    p50_ms: float = Field(description="50th percentile per-case decision latency in ms")
    p90_ms: float = Field(description="90th percentile per-case decision latency in ms")
    p95_ms: float = Field(description="95th percentile per-case decision latency in ms")
    p99_ms: float = Field(description="99th percentile per-case decision latency in ms")
    mean_ms: float = Field(description="Mean per-case decision latency in ms")


class StageTiming(BaseModel):
    """Elapsed timing and throughput metrics for a specific pipeline stage."""
    stage_name: str
    elapsed_ms: float
    throughput_cases_per_sec: float
    mean_ms_per_case: float


class MemoryMetrics(BaseModel):
    """Memory consumption profiling metrics captured via tracemalloc."""
    baseline_memory_mb: float = Field(description="Baseline memory before workload execution in MB")
    peak_memory_mb: float = Field(description="Peak allocated memory during benchmark in MB")
    incremental_memory_mb: float = Field(description="Net memory allocated during benchmark in MB")
    memory_per_case_kb: float = Field(description="Average memory allocated per case in KB")


class InferenceComparisonMetrics(BaseModel):
    """Comparative performance benchmarks: single-case inference vs. batch inference."""
    single_total_ms: float
    single_throughput_cases_per_sec: float
    single_latency_ms_per_case: float
    batch_total_ms: float
    batch_throughput_cases_per_sec: float
    batch_latency_ms_per_case: float
    speedup_factor: float


class ConfidenceInterval(BaseModel):
    """Empirical confidence interval bounds."""
    lower: float = Field(description="Lower bound of confidence interval")
    upper: float = Field(description="Upper bound of confidence interval")
    confidence_level: float = Field(default=0.95, description="Nominal confidence coverage")


class PolicyScaleMetrics(BaseModel):
    """
    Economic performance metrics for a single policy evaluated over a scale workload.
    GUARANTEE: All internal monetary quantities are strictly integer paise.
    """
    policy_name: str
    total_cases: int
    total_revenue_at_risk_paise: int

    # Financial results in integer paise
    gross_recovered_paise: int
    intervention_cost_paise: int
    net_recovered_paise: int
    delta_vs_rule_baseline_paise: int = 0
    regret_vs_oracle_paise: int = 0
    oracle_headroom_captured_pct: float = 0.0

    # Operational rates
    recovered_cases: int
    recovery_rate: float
    intervened_cases: int
    intervention_rate: float
    escalated_cases: int
    escalation_rate: float
    intervention_efficiency: float

    # Action counts breakdown
    action_counts: Dict[str, int]

    # Optional Customer-Clustered Bootstrap Confidence Intervals (in INR & %)
    ci_net_recovered_inr: Optional[ConfidenceInterval] = None
    ci_delta_vs_rule_inr: Optional[ConfidenceInterval] = None
    ci_recovery_rate_pct: Optional[ConfidenceInterval] = None
    ci_cost_inr: Optional[ConfidenceInterval] = None

    # Presentation Helpers in INR
    @property
    def total_revenue_at_risk_inr(self) -> float:
        return self.total_revenue_at_risk_paise / 100.0

    @property
    def gross_recovered_inr(self) -> float:
        return self.gross_recovered_paise / 100.0

    @property
    def intervention_cost_inr(self) -> float:
        return self.intervention_cost_paise / 100.0

    @property
    def net_recovered_inr(self) -> float:
        return self.net_recovered_paise / 100.0

    @property
    def delta_vs_rule_baseline_inr(self) -> float:
        return self.delta_vs_rule_baseline_paise / 100.0

    @property
    def regret_vs_oracle_inr(self) -> float:
        return self.regret_vs_oracle_paise / 100.0


class SubgroupMetric(BaseModel):
    """Segmented economic performance across failure types, payment methods, retry tiers, etc."""
    dimension: str
    group_key: str
    num_cases: int
    revenue_at_risk_paise: int
    net_recovered_paise: int
    recovery_rate: float
    intervention_rate: float

    @property
    def revenue_at_risk_inr(self) -> float:
        return self.revenue_at_risk_paise / 100.0

    @property
    def net_recovered_inr(self) -> float:
        return self.net_recovered_paise / 100.0


class ReproducibilityManifest(BaseModel):
    """Comprehensive environment and execution metadata ensuring exact benchmark reproducibility."""
    benchmark_version: str = "1.0.0"
    timestamp: str
    python_version: str
    platform: str
    numpy_version: str
    pandas_version: str
    scikit_learn_version: str
    model_source: str
    action_costs_paise: Dict[str, int]
    seed: int
    batch_size: int
    evaluation_mode: str = "Mode B (Scale & Stress Benchmark)"


class ScaleBenchmarkReport(BaseModel):
    """
    Master machine-readable report object for RecoverAI Milestone 7 scale evaluation.
    """
    benchmark_id: str
    dataset_metadata: Dict[str, Any]
    configuration: BenchmarkConfig
    performance: Dict[str, Any]
    policies: Dict[str, PolicyScaleMetrics]
    subgroups: Dict[str, Dict[str, SubgroupMetric]]
    reproducibility: ReproducibilityManifest
