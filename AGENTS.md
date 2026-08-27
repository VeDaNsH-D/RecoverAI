# AGENTS.md — RecoverAI Developer & Agent Guidelines

## 1. Project Mission & Identity

**RecoverAI** is an autonomous, bounded AI revenue recovery system built for the Razorpay Buildathon (Track 03: AI Revenue Recovery).

> **Core Product Promise**: *Find revenue that's slipping away and win it back.*

In modern commerce and subscription businesses, 5–15% of transactions fail due to transient technical errors, customer balance issues, outdated payment methods, or operational friction. Blanket retries or spammy notifications annoy customers, increase gateway fees, and cause churn. RecoverAI evaluates transaction context, understands failure causes, estimates expected net recovery value, selects bounded interventions, executes them safely, and measures causal incremental recovered revenue.

---

## 2. Core Architectural & Scientific Principles

1. **Primary Metric is Incremental Net Revenue Recovered ($\Delta \text{Revenue}$)**:
   - High classification accuracy or raw recovery counts are secondary. What matters is net revenue recovered over a clear baseline after accounting for intervention costs and friction.
2. **Zero Access to Hidden Ground Truth (Anti-Leakage Guarantee)**:
   - The environment contains latent variables (customer intent, true fund availability, real recovery propensity). The agent and ML models must **never** receive hidden ground-truth fields or potential outcomes during inference.
   - Ground truth is generated and held independently by the simulator.
3. **Common Random Numbers & Potential Outcomes**:
   - The simulated world pre-determines potential outcomes $Y(a)$ for each action $a$. When policies are evaluated against each other, they are tested against the exact same realization of the world to eliminate stochastic variance.
4. **Exact Financial Calculations (Integer Paise)**:
   - All internal monetary quantities (`amount_paise`, `recovered_paise`, `cost_paise`, `net_recovered_paise`) are strictly 64-bit integers in paise (1 INR = 100 paise). Float formatting is only permitted for user-facing presentations.
5. **Bounded Financial & Operational Actions**:
   - The agent cannot execute arbitrary financial transactions. Every action is chosen from a bounded action space (`no_action`, `retry`, `payment_link`, `reminder`, `escalate`) subject to hard safety policy guardrails (e.g., maximum retries, rate limits, amount limits).
6. **Strict Auditability**:
   - Every observation, decision, feature vector, policy rationale, and outcome must be logged with an immutable audit trail.
7. **Customer-Level Dataset Partitions**:
   - Train, validation, and held-out test sets are strictly partitioned at the customer level to ensure models generalize to unseen customer identities without data leakage.

---

## 3. Scope & Milestones

- **Milestone 1 (Current)**:
  - Causal synthetic payment & customer world.
  - Hidden ground truth with potential outcomes framework.
  - Strict observable feature boundary.
  - Deterministic Rule-Based Baseline Policy.
  - Evaluation Engine with Incremental Net Revenue calculations.
  - Benchmark Oracle Policy (for upper bound analysis).
  - Reproducible CLI scripts and comprehensive unit tests.
- **Future Milestones**:
  - ML predictive recovery scoring models (uplift & expected value).
  - LLM orchestrator with structured tool calling & safety policies.
  - Razorpay test-mode webhook & API integration.
  - Auditable dashboard and interactive recovery workflow.

---

## 4. Development Constraints

- **Python Version**: Python 3.10+ (Tested on Python 3.13)
- **Formatting & Typing**: Strict type annotations throughout using `pydantic` v2 and standard library dataclasses/enums.
- **Reproducibility**: Explicit random seeds for all data generation, shuffling, and outcome simulations.
