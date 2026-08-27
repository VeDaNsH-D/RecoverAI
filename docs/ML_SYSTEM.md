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

## 2. Modeling Formulation: Action-Conditional Potential-Outcome Models

### Distinction from Observational Causal Inference
In observational data, researchers must control for unobserved confounders and propensity scores because treatment assignments are selective. 

In our synthetic environment `sim_v1`:
1. Ground truth predetermines the complete potential outcome vector $\mathbf{Y}_i = (Y_i(\text{no\_action}), Y_i(\text{retry}), Y_i(\text{payment\_link}), Y_i(\text{reminder}), Y_i(\text{escalate}))$ for every case $i$.
2. For each action $a \in \mathcal{A}$, the training data provides the exact supervised realization $(X_i, Y_i(a))$.
3. We train **5 independent action-conditional models** $f_a(X) \to \hat{P}(Y(a)=1 \mid X)$.
4. Each model specializes in the specific non-linear response curve and failure-type interactions of action $a$.

---

## 3. Temporal Feature Safety & Anti-Leakage Guarantees

### Verification of Temporal Feature Safety
All customer history fields:
- `customer_historical_success_rate`
- `customer_total_transactions`
- `customer_total_failures`
- `customer_avg_amount_paise`
- `customer_tenure_months`

represent prior lifetime behavioral statistics generated at customer profile creation time. They are strictly established **at or before** the payment incident being predicted, and have zero dependence on the incident's outcome, potential outcomes, or future events.

### Strict Data Leakage Boundary
- `PaymentCase` features contain zero ground-truth probabilities, optimal actions, latent variables ($Z_{\text{intent}}, Z_{\text{funds}}$), or future outcomes.
- `FeatureExtractor` validates every input case against `OBSERVABLE_INPUT_FIELDS` and blocks any forbidden token with `DataLeakageError`.
- Potential outcomes $Y(a)$ from ground truth are strictly used as the supervised training target $y$, and **never** enter the feature matrix $X$.

---

## 4. Supervised Dataset Representation (`ml/dataset.py`)

For each split (`train`, `val`, `test`), `PotentialOutcomeDatasetBundle` produces:
- $\mathcal{D}_{\text{no\_action}} = (X, y_{\text{no\_action}})$
- $\mathcal{D}_{\text{retry}} = (X, y_{\text{retry}})$
- $\mathcal{D}_{\text{payment\_link}} = (X, y_{\text{payment\_link}})$
- $\mathcal{D}_{\text{reminder}} = (X, y_{\text{reminder}})$
- $\mathcal{D}_{\text{escalate}} = (X, y_{\text{escalate}})$

Where:
- $X \in \mathbb{R}^{N \times 24}$ (canonical observable features).
- $y_a \in \{0, 1\}^N$ (binary realized potential outcome for action $a$).
- Case IDs are retained separately for audit logs and never included in $X$.
