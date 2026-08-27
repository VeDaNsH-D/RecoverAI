# Machine Learning & Expected Net Value Decision System — RecoverAI

## 1. System Architecture & Objective

The RecoverAI ML decision layer operates strictly on observable features $X$ from `PaymentCase` to estimate the conditional recovery probability:

$$P(Y(a) = 1 \mid X)$$

for each candidate action $a \in \{\text{no\_action}, \text{retry}, \text{payment\_link}, \text{reminder}, \text{escalate}\}$.

These probabilities feed into the **Expected Net Value Decision Engine**, which selects the action maximizing expected net financial recovery in integer paise subject to hard safety policy guardrails.

```
+-------------------------------------------------------------------------------+
|                            OBSERVABLE INPUT CASE (X)                          |
|                                                                               |
|  PaymentCase:                                                                 |
|    - amount_paise (int), payment_method, failure_type, retry_count            |
|    - hours_since_failure, customer history (success rate, failures, tenure)   |
|    - is_subscription                                                          |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                         FEATURE EXTRACTOR (ml/features.py)                    |
|                                                                               |
|  - Validates case against strict observable allowlist (Fail-Closed)           |
|  - Deterministic transformations (log scalings, one-hot encodings, ratios)   |
|  - Produces immutable 24-dimensional feature vector X                         |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                 ACTION-CONDITIONAL POTENTIAL-OUTCOME MODELS                   |
|                                                                               |
|  For each candidate action a in A:                                            |
|    X -> Model_a -> P_hat(Y(a) = 1 | X)                                        |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                 EXPECTED NET VALUE ENGINE (ml/decision_engine.py)             |
|                                                                               |
|  For each candidate action a:                                                 |
|    Expected Gross (paise) = floor(P_hat(Y(a)=1 | X) * amount_paise)           |
|    Expected Net (paise)   = Expected Gross - ACTION_COSTS_PAISE[a]            |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                         SAFETY & POLICY GUARDRAILS                            |
|                                                                               |
|  - NO_ACTION is ALWAYS available (lower bound safety fallback)                |
|  - If retry_count >= 2: RETRY is suppressed (allowed: no_action, link, etc.)  |
|  - If amount < INR 200: ESCALATE is suppressed (prevents fee burning)         |
|  - Decision: argmax_{a in Allowed} Expected Net (paise)                       |
+-------------------------------------------------------------------------------+
```

---

## 2. Expected Net Value Formulation & Authoritative Action Costs

### Mathematical Formulation
For each candidate action $a \in \mathcal{A}$ on case $i$:
1. **Predicted Recovery Probability**: $\hat{P}_i(a) = \hat{P}(Y_i(a) = 1 \mid X_i) \in [0.0, 1.0]$.
2. **Expected Gross Revenue (Paise)**:
   $$\hat{\mathbb{E}}[\text{Gross}_i(a)] = \lfloor \hat{P}_i(a) \times \text{amount\_paise}_i \rfloor$$
3. **Expected Net Revenue (Paise)**:
   $$\hat{\mathbb{E}}[\text{Net}_i(a)] = \hat{\mathbb{E}}[\text{Gross}_i(a)] - \text{ACTION\_COSTS\_PAISE}[a]$$
4. **Optimal Bounded Selection**:
   $$a_i^* = \arg\max_{a \in \mathcal{A}_{\text{allowed}}(i)} \hat{\mathbb{E}}[\text{Net}_i(a)]$$
   *Tie-breaking*: Deterministic priority order `[no_action, retry, payment_link, reminder, escalate]`.

### Authoritative Friction Costs (`simulator.config.ACTION_COSTS_PAISE`)
- `no_action`: **0 paise** (₹0.00) — Passive observation baseline.
- `retry`: **200 paise** (₹2.00) — Automated gateway retry overhead.
- `payment_link`: **1,000 paise** (₹10.00) — Communication channel cost + user friction.
- `reminder`: **500 paise** (₹5.00) — Notification / reminder friction.
- `escalate`: **5,000 paise** (₹50.00) — Manual operations and agent intervention overhead.

---

## 3. Safety Guardrails & Policy Constraints

1. **`NO_ACTION` Invariant**: `NO_ACTION` is **always allowed** across all cases. If all intervention actions yield negative expected net value ($\hat{\mathbb{E}}[\text{Net}](a) < 0$), the engine selects `NO_ACTION`.
2. **Maximum Retry Protection**: If `retry_count >= 2`, `RETRY` is disqualified. The engine chooses among `[no_action, payment_link, reminder, escalate]`.
3. **Micro-Ticket Protection**: If `amount_paise < 20,000` (₹200), `ESCALATE` is disqualified to prevent spending ₹50 on low-ticket recoveries.

---

## 4. Decision Margin & Regret Metrics

- **Decision Margin**: The difference in expected net payoff between the selected best action and the second-best allowed action:
  $$\text{Margin}_i = \hat{\mathbb{E}}[\text{Net}_i(a^*)] - \max_{a \in \mathcal{A}_{\text{allowed}} \setminus \{a^*\}} \hat{\mathbb{E}}[\text{Net}_i(a)]$$
  Higher margins indicate higher decision confidence and economically meaningful trade-offs.
- **Regret vs. Oracle**: The economic opportunity loss compared to the omniscient ground-truth policy under identical realized potential outcomes:
  $$\text{Regret} = \text{Net}_{\text{oracle}} - \text{Net}_{\text{policy}}$$

---

## 5. Validation Economic Decision Comparison (Validation Split — 1,500 Cases)

Revenue at Risk: **₹4,487,368.00** (448,736,800 paise).

```
===================================================================================================================
 RECOVERAI VALIDATION DECISION COMPARISON (SPLIT: VAL -- 1,500 Cases | Revenue at Risk: INR 4,487,368.00)
===================================================================================================================
Policy / Engine           |  Net Rec (INR) | Gross Rec (INR) |   Cost (INR) |   Delta vs Rule | Regret vs Oracle | Rec Rate | Int Rate
-------------------------------------------------------------------------------------------------------------------
Rule Baseline             | INR 2,918,209.00 | INR 2,937,689.00 | INR 19,480.00 |              -- |   INR 107,186.00 |    66.5% |   100.0%
Logistic Decision Engine  | INR 3,005,931.00 | INR 3,032,939.00 | INR 27,008.00 | +INR 87,722.00 (+3.01%) |    INR 19,464.00 |    68.9% |   100.0%
GBM Decision Engine       | INR 2,944,316.00 | INR 2,974,265.00 | INR 29,949.00 | +INR 26,107.00 (+0.89%) |    INR 81,079.00 |    67.5% |   100.0%
Oracle                    | INR 3,025,395.00 | INR 3,049,593.00 | INR 24,198.00 | +INR 107,186.00 (+3.67%) |         INR 0.00 |    69.3% |    88.5%
===================================================================================================================
```

### Action Distributions
- **Rule Baseline**: `retry`: 38.0%, `payment_link`: 46.9%, `escalate`: 15.1%, `reminder`: 0.0%, `no_action`: 0.0%.
- **Logistic Decision Engine**: `retry`: 27.6%, `payment_link`: 39.7%, `escalate`: 26.3%, `reminder`: 6.4%, `no_action`: 0.0%.
- **GBM Decision Engine**: `retry`: 24.1%, `payment_link`: 41.4%, `escalate`: 30.3%, `reminder`: 4.2%, `no_action`: 0.0%.
- **Oracle**: `retry`: 23.9%, `payment_link`: 35.5%, `escalate`: 23.7%, `reminder`: 5.5%, `no_action`: 11.5%.

### Internal Decision Engine Economics
- **Logistic Decision Engine**: Average Expected Net = **₹2,116.62** | Average Decision Margin = **₹373.16**.
- **GBM Decision Engine**: Average Expected Net = **₹1,998.99** | Average Decision Margin = **₹240.36**.

---

## 6. Subgroup Economic Insights

```
--- FAILURE TYPE ---
Subgroup                   |       Rule Net |   Logistic Net |        GBM Net |     Oracle Net |  Logistic Uplift
---------------------------------------------------------------------------------------------------------
insufficient_funds         | INR 898,045.00 | INR 879,403.00 | INR 856,231.00 | INR 899,551.00 | -INR 18,642.00 (-2.1%)
invalid_payment_method     | INR 646,279.00 | INR 641,726.00 | INR 640,850.00 | INR 623,217.00 | -INR 4,553.00 (-0.7%)
temporary_failure          | INR 911,515.00 | INR 1,022,392.00 | INR 986,337.00 | INR 1,040,165.00 | +INR 110,877.00 (+12.2%)
unknown_failure            | INR 462,370.00 | INR 462,410.00 | INR 460,898.00 | INR 462,462.00 | +INR 40.00 (+0.0%)

--- RETRY COUNT ---
Subgroup                   |       Rule Net |   Logistic Net |        GBM Net |     Oracle Net |  Logistic Uplift
---------------------------------------------------------------------------------------------------------
retries_0                  | INR 2,052,660.00 | INR 2,023,459.00 | INR 1,986,542.00 | INR 2,044,543.00 | -INR 29,201.00 (-1.4%)
retries_1                  | INR 596,218.00 | INR 624,069.00 | INR 602,531.00 | INR 616,239.00 | +INR 27,851.00 (+4.7%)
retries_2                  | INR 159,040.00 | INR 248,384.00 | INR 245,445.00 | INR 253,552.00 | +INR 89,344.00 (+56.2%)
retries_3                  | INR 110,291.00 | INR 110,019.00 | INR 109,798.00 | INR 111,061.00 | -INR 272.00 (-0.2%)

--- SUBSCRIPTION STATUS ---
Subgroup                   |       Rule Net |   Logistic Net |        GBM Net |     Oracle Net |  Logistic Uplift
---------------------------------------------------------------------------------------------------------
one_off                    | INR 2,354,004.00 | INR 2,372,408.00 | INR 2,357,451.00 | INR 2,388,327.00 | +INR 18,404.00 (+0.8%)
subscription               | INR 564,205.00 | INR 633,523.00 | INR 586,865.00 | INR 637,068.00 | +INR 69,318.00 (+12.3%)
```

### Key Takeaway
The decision engine creates massive economic alpha by intelligently switching away from dead-end retries when `retry_count >= 2` (**+₹89,344.00 / +56.2% uplift**) and optimizing high-value interventions on recurring subscriptions (**+₹69,318.00 / +12.3% uplift**).
