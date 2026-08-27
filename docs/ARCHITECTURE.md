# System Architecture Document — RecoverAI

## 1. System Overview & Boundaries

The RecoverAI architecture is structured into decoupled layers with strict separation between the **Simulated Environment (Hidden Ground Truth)**, the **Observable Domain (Agent/ML Features)**, the **Decision/Policy Engine**, and the **Evaluation Framework**.

```
+-----------------------------------------------------------------------------------+
|                            SIMULATOR & WORLD ENGINE                               |
|                                                                                   |
|  +---------------------------+             +-----------------------------------+  |
|  | Customer & Case Generator |             | Hidden Ground Truth Generator     |  |
|  |  - 2,000 Customers        |             |  - Latent states (intent, funds)  |  |
|  |  - 10,000 Cases           |             |  - Potential Outcomes Y(a)        |  |
|  +-------------+-------------+             |  - Common Random Numbers          |  |
|                |                           +-----------------+-----------------+  |
|                |                                             |                    |
+----------------|---------------------------------------------|--------------------+
                 | (Observable features ONLY)                  | (Ground Truth ONLY)
                 v                                             v
+------------------------------------+       +--------------------------------------+
|       OBSERVABLE FEATURE LAYER     |       |          OUTCOME SIMULATOR           |
|                                    |       |                                      |
|  PaymentCase:                      |       |  Evaluates chosen Action 'a' against |
|   - case_id, customer_id           |       |  pre-generated potential outcome     |
|   - amount_paise (int)             |       |  Y(a) in CaseGroundTruth.            |
|   - failure_type, payment_method   |       |                                      |
|   - customer_history, retry_count  |       |  Calculates:                         |
|   - hours_since_failure            |       |   - recovered: bool                  |
|                                    |       |   - recovered_paise: int             |
|  (ZERO access to ground truth)     |       |   - cost_paise: int                  |
+----------------+-------------------+       |   - net_recovered_paise: int         |
                 |                           |   - latency_hours: float             |
                 v                           +------------------+-------------------+
+------------------------------------+                          ^
|          POLICY ENGINE             |                          |
|                                    |                          |
|  - NoActionPolicy                  |                          |
|  - RuleBasedBaselinePolicy         |                          |
|  - (Future ML / Agent Policy)      |                          |
|                                    |                          |
|  Decision: Action 'a' -------------+--------------------------+
+------------------------------------+
                 |
                 v
+-----------------------------------------------------------------------------------+
|                                EVALUATION ENGINE                                  |
|                                                                                   |
|  - Compares: NoAction vs Baseline vs Future ML vs Oracle                         |
|  - Calculates: Total Revenue at Risk, Total Recovered, Incremental Net Revenue     |
|  - Outputs: JSON, CSV, Rich Console Markdown Report                               |
+-----------------------------------------------------------------------------------+
```

---

## 2. Anti-Leakage & Ground-Truth Isolation

### 2.1 Observable Schema (`PaymentCase`)
The observable schema contains strictly what a real payment gateway (e.g. Razorpay) or merchant billing backend provides:
- Identifiers: `case_id`, `customer_id`, `merchant_id`
- Financial: `amount_paise` (int), `currency` (INR)
- Failure Context: `failure_type`, `payment_method`, `retry_count`, `hours_since_failure`
- Customer Context: `customer_historical_success_rate`, `customer_total_transactions`, `customer_total_failures`, `customer_avg_amount_paise`, `is_subscription`

### 2.2 Hidden Ground Truth (`CaseGroundTruth`)
Ground truth contains latent variables that exist in the real world but are unobservable directly:
- `recovery_probabilities`: True conditional probability $P(Y(a)=1 \mid X, Z)$ for each action $a$.
- `potential_outcomes`: The realization $Y(a) \in \{0, 1\}$ for each action under common random numbers.
- `latent_customer_intent`: Unobservable customer willingness to pay $[0, 1]$.
- `latent_funds_availability`: Unobservable customer liquidity $[0, 1]$.
- `optimal_action`: Theoretical action maximizing expected net payoff.
- `max_sensible_retries`: Maximum safe retries before customer churn or fraud block.

> **Security Contract**: Policies and ML feature pipelines ingest exclusively `PaymentCase`. `CaseGroundTruth` is only passed to `OutcomeSimulator` and `OraclePolicy` (which exists solely as an evaluation benchmark).

---

## 3. Potential Outcomes & Common Random Numbers (CRN)

To ensure policy comparisons evaluate policy decision quality rather than stochastic simulation luck:
1. When a dataset is generated with seed $S$, the latent threshold $\xi_{i, a} \sim U(0, 1)$ is sampled deterministically for every case $i$ and action $a$.
2. The potential outcome is fixed:
   $$Y_i(a) = \mathbb{I}\left(\xi_{i, a} \le P(Y_i(a)=1 \mid X_i, Z_i)\right)$$
3. If Policy A and Policy B both choose `retry` on case $i$, they observe the exact same outcome $Y_i(\text{retry})$.
4. If Policy A chooses `retry` and Policy B chooses `payment_link`, their outcomes are evaluated against the predetermined potential outcomes $Y_i(\text{retry})$ and $Y_i(\text{payment\_link})$.

---

## 4. Integer Currency Standard (Zero Float Drift)

All internal monetary calculations are conducted in integer **paise** (1 INR = 100 paise).
- `amount_paise: int`
- `cost_paise: int`
- `recovered_paise: int`
- `net_recovered_paise = recovered_paise - cost_paise`
- Presentation layers convert paise to rupees via: `paise / 100.0` or formatting string `f"₹{paise / 100:,.2f}"`.

---

## 5. Dataset Splitting Strategy

Partitions are generated at the **customer level**:
- `train` (70% of customers $\to$ all their cases)
- `val` (15% of customers $\to$ all their cases)
- `test` (15% of customers $\to$ all their cases)

This guarantees that evaluation on `test` reflects true out-of-sample generalization to new customers without leaking behavioral history.
