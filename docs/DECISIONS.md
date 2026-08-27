# Architecture Decision Records (ADRs) — RecoverAI

## ADR 001: Strict Schema Separation between Observable Features and Hidden Ground Truth
- **Status**: Accepted
- **Context**: In real-world payment environments, the true underlying probability of a customer paying or the true root cause is never known with certainty. In synthetic simulations, there is a severe danger of data leakage if the model or agent is passed objects containing ground-truth recovery probabilities, optimal actions, or latent states.
- **Decision**: Define two completely separate schemas:
  - `PaymentCase`: Contains only observable features (amount, history, failure type, retry count, time elapsed).
  - `CaseGroundTruth`: Contains hidden latent variables and potential outcomes.
  - Policy interfaces accept only `PaymentCase`. Ground truth is held exclusively by the evaluator and outcome simulator.
- **Consequences**: Guarantees zero data leakage. Enables realistic generalization testing.

---

## ADR 002: Exact Integer Paise Monetary Arithmetic
- **Status**: Accepted
- **Context**: Floating-point representations (e.g. `0.1 + 0.2 != 0.3`) accumulate rounding errors in financial ledgers and can cause discrepancies during aggregation.
- **Decision**: All internal monetary values are stored and calculated as 64-bit integer paise (1 INR = 100 paise).
  - `amount_paise: int`
  - `cost_paise: int`
  - `recovered_paise: int`
  - `net_recovered_paise: int`
  Decimal/float formatting is strictly isolated to the user interface/reporting layer.
- **Consequences**: 100% exact mathematical precision across all revenue aggregations.

---

## ADR 003: Potential Outcomes Framework & Common Random Numbers (CRN)
- **Status**: Accepted
- **Context**: If policy outcomes are sampled independently on the fly during evaluation, stochastic simulation variance could falsely reward or penalize a policy.
- **Decision**: For every case $i$, generate fixed potential outcomes $Y_i(a) \in \{0, 1\}$ for all available actions $a \in \mathcal{A}$ using deterministic random thresholds sampled at dataset generation time.
- **Consequences**: Every policy evaluated against the dataset experiences the exact same underlying realization of the synthetic world. Differences in policy returns represent genuine decision quality.

---

## ADR 004: Customer-Level Dataset Partitioning
- **Status**: Accepted
- **Context**: If cases from the same customer are randomly split across train and test sets, the model could memorize customer behavioral profiles, artificially inflating test metrics.
- **Decision**: Partitions (`train` 70%, `val` 15%, `test` 15%) are created by partitioning customer IDs. All cases for a given customer belong strictly to a single split.
- **Consequences**: Ensures that evaluation on the test split measures true out-of-sample generalization to new customers.

---

## ADR 005: Definition of Benchmark Policies (No Action, Rule Baseline, Oracle)
- **Status**: Accepted
- **Context**: We need unambiguous reference points to measure incremental recovery value.
- **Decision**:
  - `NoActionPolicy`: Represents passive default behavior (lower bound).
  - `RuleBasedBaselinePolicy`: Represents standard industry heuristic retries/links (the benchmark to beat).
  - `OraclePolicy`: An evaluator-only policy with access to ground truth that selects the action maximizing expected net payoff (theoretical upper bound).
- **Consequences**: Establishes a rigorous spectrum $[\text{NoAction}, \text{Baseline}, \dots, \text{Oracle}]$ against which ML and AI Agent policies are judged.

---

## ADR 006: Synthetic Simulation Assumptions for Action Costs & Latencies
- **Status**: Accepted
- **Context**: Action costs (e.g. ₹2 for retry, ₹10 for link, ₹50 for escalation) are required to calculate net revenue recovery.
- **Decision**: Clearly document that action costs and latencies are synthetic benchmark assumptions designed to reflect operational, communication, and human intervention friction, and do not represent actual Razorpay commercial pricing.
- **Consequences**: Prevents confusion regarding Razorpay fee schedules while maintaining economic realism.
