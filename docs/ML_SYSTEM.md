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
In observational payment datasets, researchers must model treatment propensity scores $P(A \mid X)$ because treatment assignments are selective and confounded.

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

## 4. Model Architectures & Calibration Protocol

### A. Logistic Regression Baseline (`LogisticRecoveryModel`)
- Standardizes features via `StandardScaler`.
- Applies L2 regularization ($C=1.0$) with L-BFGS solver.
- Calibrated via internal 5-fold cross-validation Platt scaling (`CalibratedClassifierCV(method='sigmoid', cv=5)`).
- Serves as the transparent, convex baseline.

### B. Gradient Boosted Model (`GBMRecoveryModel`)
- Uses `HistGradientBoostingClassifier` with max 100 iterations, learning rate 0.08, min 20 samples per leaf, and L2 regularization 1.0.
- Models complex non-linear retry-fatigue curves, amount thresholds, and interaction terms.
- Calibrated via internal 5-fold cross-validation Platt scaling (`CalibratedClassifierCV(method='sigmoid', cv=5)`).

### Strict Calibration Boundary
- **TRAIN Split**: Used exclusively for model fitting and internal cross-validation probability calibration.
- **VAL Split**: Used exclusively for out-of-sample predictive diagnostics (Log Loss, Brier Score, ROC-AUC, ECE) and model selection.
- **TEST Split**: Kept 100% untouched until final benchmark evaluation.

---

## 5. Validation Predictive Diagnostics (Validation Split — 1,500 Cases)

```
===============================================================================================
 RECOVERAI ML VALIDATION DIAGNOSTIC REPORT (SPLIT: VAL -- 1,500 Cases)
===============================================================================================
Action           | Model Type             |  Log Loss | Brier Score |  ROC-AUC |     ECE | Pos Rate
-----------------------------------------------------------------------------------------------
no_action        | logistic_regression    |    0.1093 |      0.0247 |   0.7759 |  0.0020 |    2.60%
no_action        | hist_gradient_boosting |    0.1099 |      0.0249 |   0.7673 |  0.0051 |    2.60%
-----------------------------------------------------------------------------------------------
retry            | logistic_regression    |    0.3448 |      0.1113 |   0.8856 |  0.0196 |   24.80%
retry            | hist_gradient_boosting |    0.3552 |      0.1146 |   0.8798 |  0.0335 |   24.80%
-----------------------------------------------------------------------------------------------
payment_link     | logistic_regression    |    0.6552 |      0.2314 |   0.6295 |  0.0184 |   58.27%
payment_link     | hist_gradient_boosting |    0.6648 |      0.2361 |   0.6079 |  0.0262 |   58.27%
-----------------------------------------------------------------------------------------------
reminder         | logistic_regression    |    0.5431 |      0.1822 |   0.7423 |  0.0423 |   32.53%
reminder         | hist_gradient_boosting |    0.5584 |      0.1887 |   0.7214 |  0.0257 |   32.53%
-----------------------------------------------------------------------------------------------
escalate         | logistic_regression    |    0.6350 |      0.2222 |   0.6601 |  0.0243 |   59.67%
escalate         | hist_gradient_boosting |    0.6431 |      0.2261 |   0.6399 |  0.0256 |   59.67%
-----------------------------------------------------------------------------------------------
===============================================================================================
```
