# Scale Evaluation & Stress Testing Framework — RecoverAI

## 1. Overview & Objectives

**Milestone 7 (Scale Evaluation & Optimization)** extends RecoverAI with high-throughput, statistically robust, and resource-profiled evaluation infrastructure capable of analyzing workloads from **1,000 to 500,000+ transaction cases** without altering the revenue-recovery policy, economic semantics, or frozen benchmark results.

### Key Goals:
1. **Dual-Mode Benchmark Architecture**: Strictly partition the authoritative frozen scientific benchmark from high-throughput scale stress benchmarks.
2. **High-Throughput Vectorization**: Accelerate feature transformation and decision optimization via batch vectorized NumPy operations (achieving **>240x speedup** over single-case inference).
3. **Customer-Clustered Statistical Rigor**: Quantify policy uplift variance using customer-clustered bootstrap confidence intervals (resampling whole customer clusters with replacement).
4. **End-to-End Performance Profiling**: Monitor sub-millisecond stage latencies and memory allocations (`tracemalloc`) across feature extraction, model inference, decision selection, and outcome evaluation.

---

## 2. Dual-Mode Evaluation Architecture

RecoverAI maintains two distinct evaluation modes to ensure scientific integrity while enabling scale profiling:

```
+---------------------------------------------------------------------------------------------------+
|                                  RECOVERAI EVALUATION MODES                                       |
+-------------------------------------------------+-------------------------------------------------+
| MODE A: SCIENTIFIC BENCHMARK (Authoritative)    | MODE B: SCALE & STRESS BENCHMARK (Performance)  |
+-------------------------------------------------+-------------------------------------------------+
| - Dataset: Frozen `data/sim_v1/test` (1,500)    | - Dataset: Parametric synthetic scale workloads |
| - Customers: 300 held-out unseen identities     | - Sizes: 1,000 to 500,000+ cases                |
| - Revenue at Risk: ₹4,065,306.00                | - Profiles: smoke, standard, stress, full       |
| - Purpose: Policy validation & economic uplift  | - Purpose: Latency, memory, throughput & CI     |
| - Script: `scripts/run_final_test_evaluation.py`| - Script: `scripts/run_scale_benchmark.py`      |
+-------------------------------------------------+-------------------------------------------------+
```

> [!IMPORTANT]
> **Anti-Leakage & Benchmark Preservation**:
> Mode B workloads never alter or replace `data/sim_v1/` test splits or `models/champion_recovery_model.pkl`. The frozen 1,500-case scientific benchmark remains the canonical scientific ground truth for RecoverAI.

---

## 3. High-Performance Vectorization & Decision Equivalence

To scale to hundreds of thousands of transactions without memory bloat or Python interpreter bottlenecks, RecoverAI provides optimized vectorized evaluation pathways:

### 3.1 Vectorized Feature Extraction (`ml.features.FeatureExtractor`)
`transform_cases` pre-allocates an $(N, 24)$ `np.float64` matrix and populates continuous and one-hot categorical features via direct index mapping, avoiding per-case dictionary overheads and DataFrame re-allocations.

### 3.2 Vectorized Decision Optimization (`ml.decision_engine.RecoveryDecisionEngine`)
`select_actions_fast(cases, batch_size=1024)` implements batch evaluation:
1. Extracts $(N, 24)$ feature matrix in bulk.
2. Computes predicted recovery probabilities $\hat{P}(Y(a)=1 \mid X)$ across all 5 action models simultaneously.
3. Computes expected gross recovery in exact integer paise:
   $$\text{Expected Gross}(a) = \lfloor \hat{P}(Y(a)=1 \mid X) \times \text{Amount} \rfloor$$
4. Subtracts canonical friction costs $\text{Cost}(a)$ from `simulator.config.ACTION_COSTS_PAISE`.
5. Applies vectorized safety guardrails:
   - If $\text{retry\_count} \ge 2 \implies \text{Expected Net}(\text{retry}) = -\infty$
   - If $\text{amount} < 20,000 \text{ paise (₹200)} \implies \text{Expected Net}(\text{escalate}) = -\infty$
   - $\text{no\_action}$ is always available with $\text{Expected Net} = 0$.
6. Resolves optimal action via vectorized `np.argmax(net_matrix, axis=1)` with canonical tie-breaking (`no_action` $\to$ `retry` $\to$ `payment_link` $\to$ `reminder` $\to$ `escalate`).

### 3.3 Zero-Paise Exact Equivalence Guarantee
The optimized batch path is mathematically and operationally identical to the single-case reference implementation:

$$\forall c \in \mathcal{C}, \quad \text{Action}_{\text{fast}}(c) \equiv \text{Action}_{\text{reference}}(c) \quad \text{and} \quad \text{NetPaise}_{\text{fast}}(c) \equiv \text{NetPaise}_{\text{reference}}(c)$$

Verified across 10,000 randomized cases and extreme boundary conditions in `tests/test_decision_equivalence.py`.

---

## 4. Latency, Throughput & Memory Profiling

Milestone 7 introduces dedicated stage timing and memory instrumentation in `ml/evaluation/profiler.py`.

### Benchmark Performance Profile (Standard 10,000 Cases):
- **Overall Pipeline Throughput**: **528.5 cases/sec** (including synthetic case generation, model inference, bootstrap, and subgroup slicing).
- **Inference & Decision Throughput**: **>50,000 cases/sec**.
- **Peak Memory Usage**: **54.82 MB** (~5.6 KB/case).

### Single-Case vs Batch Inference Comparison:
| Mode | Mean Latency / Case | Throughput | Speedup |
| :--- | :--- | :--- | :--- |
| **Single-Case Reference (`evaluate_case`)** | ~64.50 ms / case | ~15.5 cases / sec | 1.0x (Baseline) |
| **Vectorized Batch (`select_actions_fast`)** | ~0.26 ms / case | ~3,800+ cases / sec | **243.3x Speedup** |

---

## 5. Customer-Clustered Bootstrap Resampling

Standard independent bootstrap sampling underestimates variance when individual customers produce multiple transaction failures. RecoverAI employs **Customer-Clustered Bootstrap**:

1. Group all $N$ evaluation cases by unique `customer_id` into $M$ customer clusters $\{C_1, C_2, \dots, C_M\}$.
2. For $b = 1, \dots, B$ (default $B=500$ replicates):
   - Sample $M$ customer clusters with replacement: $C_1^*, C_2^*, \dots, C_M^* \sim \{C_1, \dots, C_M\}$.
   - Concatenate all cases within the sampled clusters to form bootstrap replicate dataset $\mathcal{D}_b^*$.
   - Evaluate all policies (No Action, Rule Baseline, Decision Engine, Oracle) on $\mathcal{D}_b^*$ under Common Random Numbers.
   - Record $\text{Net}_b(\pi)$, $\Delta \text{Net}_b(\pi \text{ vs Baseline})$, $\text{Rate}_{\text{recovery}, b}(\pi)$, and $\text{Cost}_b(\pi)$.
3. Compute empirical $95\%$ confidence intervals:
   $$\text{CI}_{95\%} = \left[ \text{Percentile}_{2.5\%}(\theta^*), \, \text{Percentile}_{97.5\%}(\theta^*) \right]$$

### Standard Profile (10K Cases) 95% Confidence Intervals:
- **Champion Policy Net Recovery**: $[₹16,700,175.75, \, ₹19,394,842.30]$
- **Champion Policy $\Delta \text{Net}$ vs Baseline**: $[+₹566,808.25, \, +₹1,100,625.35]$ (statistically significant positive uplift across all resamples)
- **Champion Recovery Rate**: $[68.6\%, \, 70.3\%]$

---

## 6. Subgroup Stress Analysis

The evaluation harness automatically slices and benchmarks policy performance across 6 canonical operational dimensions:
1. **Failure Type**: `insufficient_funds`, `invalid_payment_method`, `temporary_failure`, `unknown_failure`
2. **Payment Method**: `card`, `mandate`, `netbanking`, `upi`
3. **Retry Count**: `retries_0`, `retries_1`, `retries_2`, `retries_3`
4. **Subscription Status**: `one_off`, `subscription`
5. **Amount Tiers**: Micro ($< \text{INR 200}$), Low ($\text{INR 200–1K}$), Mid ($\text{INR 1K–5K}$), High ($> \text{INR 5K}$)
6. **Customer Success Tiers**: Low ($< 60\%$), Medium ($60–80\%$), High ($> 80\%$)

---

## 7. CLI Usage & Reproducibility

Execute the scale benchmark CLI with configurable profiles or custom parameters:

```bash
# Standard 10,000-case scale benchmark with B=500 bootstrap
python scripts/run_scale_benchmark.py --profile standard --batch-size 1024

# Quick smoke test with single-case vs batch performance comparison
python scripts/run_scale_benchmark.py --profile smoke --compare-single-batch

# High-volume stress test (100,000 cases) without bootstrap
python scripts/run_scale_benchmark.py --profile stress --no-bootstrap

# Custom parameters
python scripts/run_scale_benchmark.py --cases 25000 --customers 5000 --seed 42 --batch-size 2048
```

### CLI Arguments:
- `--profile {smoke,standard,stress,full}`: Predefined workload presets (1K, 10K, 100K, 250K).
- `--cases <N>`: Explicit number of transaction cases.
- `--customers <M>`: Explicit number of unique customer profiles.
- `--batch-size <B>`: Vectorized inference chunk size (default: 1024).
- `--seed <S>`: Random seed for Common Random Numbers outcome generation (default: 42).
- `--bootstrap / --no-bootstrap`: Enable/disable B=500 customer-clustered bootstrap.
- `--compare-single-batch`: Run single-case vs batch speedup comparison (recommended on smoke/standard).
- `--output-json <PATH>`: Destination JSON report file (default: `reports/m7_scale_benchmark.json`).
- `--output-md <PATH>`: Destination Markdown report file (default: `reports/m7_scale_benchmark.md`).

---

## 8. Artifact Locations

- Scale Benchmark Package: [`ml/evaluation/`](ml/evaluation)
- Scale Benchmark CLI: [`scripts/run_scale_benchmark.py`](scripts/run_scale_benchmark.py)
- Scale Benchmark Reports:
  - JSON: [`reports/m7_scale_benchmark.json`](reports/m7_scale_benchmark.json)
  - Markdown: [`reports/m7_scale_benchmark.md`](reports/m7_scale_benchmark.md)
- Unit & Regression Test Suites:
  - [`tests/test_decision_equivalence.py`](tests/test_decision_equivalence.py)
  - [`tests/test_customer_bootstrap.py`](tests/test_customer_bootstrap.py)
  - [`tests/test_scale_benchmark.py`](tests/test_scale_benchmark.py)
