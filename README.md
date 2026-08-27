# RecoverAI — Autonomous AI Revenue Recovery Engine

> **Core Product Promise**: *Find revenue that's slipping away and win it back.*

Built for the **Razorpay Buildathon (Track 03: AI Revenue Recovery)**.

---

## 1. Overview & Problem

In modern commerce and subscription businesses, **5–15% of transactions fail** due to transient technical errors, customer balance issues, outdated payment methods, or operational friction. 

Standard industry recovery approaches rely on crude heuristics:
- **Blanket Retries**: Spam gateways, burn API retry fees, and degrade bank health scores without addressing customer root cause.
- **Spam Notifications**: Send premature payment links or generic reminders that annoy customers and increase churn.
- **Manual Escalations**: Deploy expensive support operations on low-value tickets where operational friction exceeds the transaction value.

**RecoverAI** replaces static heuristics with an **economically bounded, causal machine learning decision engine**. It evaluates observable payment context, predicts action-conditional recovery probabilities $P(Y(a)=1 \mid X)$, computes expected net recovery in integer paise, and executes interventions bounded by hard safety guardrails.

---

## 2. System Architecture & Flow

```
+-------------------------------------------------------------------------------+
|                       1. OBSERVABLE PAYMENT INCIDENT (X)                      |
|                                                                               |
|  PaymentCase:                                                                 |
|    - amount_paise (int), payment_method, failure_type, retry_count            |
|    - hours_since_failure, customer history (success rate, failures, tenure)   |
|    - is_subscription                                                          |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                    2. LEAKAGE-SAFE FEATURE EXTRACTION (24D)                   |
|                                                                               |
|  - Validates case against strict observable allowlist (Fail-Closed)           |
|  - Deterministic transformations (log amounts, elapsed time, one-hot encodings)|
|  - Zero access to hidden ground truth, latent states, or future outcomes      |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|              3. ACTION-CONDITIONAL POTENTIAL-OUTCOME MODELS                   |
|                                                                               |
|  For each candidate action a in {no_action, retry, link, reminder, escalate}: |
|    X -> Model_a -> P_hat(Y(a)=1 | X) in [0.0, 1.0]                           |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                 4. EXPECTED NET VALUE ENGINE (Exact Integer Paise)            |
|                                                                               |
|  For each candidate action a:                                                 |
|    Expected Gross (paise) = floor(P_hat(Y(a)=1 | X) * amount_paise)           |
|    Expected Net (paise)   = Expected Gross - ACTION_COSTS_PAISE[a]            |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                       5. SAFETY GUARDRAILS & POLICY CONSTRAINTS               |
|                                                                               |
|  - NO_ACTION is ALWAYS available (lower bound safety fallback)                |
|  - If retry_count >= 2: RETRY is suppressed (prevents gateway fatigue)        |
|  - If amount < INR 200: ESCALATE is suppressed (prevents fee burning)         |
|  - Decision: argmax_{a in Allowed} Expected Net (paise)                       |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                       6. AUDITABLE DECISION & EXPLANATION                     |
|                                                                               |
|  - Selected Action, Expected Net Value (INR & Paise), Decision Margin         |
|  - Full Action Economics & Safety Audit Ledger                                |
+-------------------------------------------------------------------------------+
```

---

## 3. Benchmark Results on Held-Out Test Set (1,500 Cases)

Evaluated under **Common Random Numbers (CRN)** on the frozen `sim_v1` held-out test split (1,500 unseen cases across 300 unseen customers, **₹4,065,306.00 at risk**):

| Policy / Engine | Net Recovery (INR) | Gross Recovery (INR) | Cost (INR) | Delta vs Rule Baseline | Regret vs Oracle | Recovery Rate | Intervention Rate | Oracle Headroom Captured |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **No Action** | ₹66,517.00 | ₹66,517.00 | ₹0.00 | -₹2,638,788.00 (-97.54%) | ₹2,936,714.00 | 2.7% | 0.0% | -885.7% |
| **Rule Baseline** | ₹2,705,305.00 | ₹2,724,137.00 | ₹18,832.00 | -- | ₹297,926.00 | 69.2% | 100.0% | -- |
| **Logistic Decision Engine (Champion)** | **₹2,946,931.00** | **₹2,972,057.00** | **₹25,126.00** | **+₹241,626.00 (+8.93%)** | **₹56,300.00** | **71.3%** | **100.0%** | **81.1%** |
| **GBM Decision Engine** | ₹2,831,319.00 | ₹2,859,193.00 | ₹27,874.00 | +₹126,014.00 (+4.66%) | ₹171,912.00 | 69.6% | 100.0% | 42.3% |
| **Oracle (Benchmark Ceiling)** | ₹3,003,231.00 | ₹3,025,648.00 | ₹22,417.00 | +₹297,926.00 (+11.01%) | ₹0.00 | 72.9% | 88.5% | 100.0% |

### Key Takeaways
- **Massive Causal Uplift**: The Champion Logistic Decision Engine captures **+₹241,626.00 (+8.93%) incremental net recovery** over standard heuristic retries.
- **Oracle Headroom Capture**: Captures **81.1% of the total theoretical headroom** available in the environment.
- **Subgroup Alpha**:
  - **Exhausted Retries (`retries == 2`)**: **+56.2% net recovery uplift** by recognizing gateway exhaustion and pivoting to payment links/escalation.
  - **Recurring Subscriptions**: **+12.3% net recovery uplift** on mandate and card SaaS billing.
  - **Temporary Failures**: **+12.2% net recovery uplift**.

---

## 4. Quickstart & CLI Commands

### A. Run Interactive Demo
Demonstrates real-time observable inference and auditable decision reports across 8 failure scenarios:
```bash
python scripts/demo.py
```

### B. Run Full Test Suite (51 Tests)
```bash
python -m pytest tests/ -v
```

### C. Run Validation Decision Diagnostics
```bash
python scripts/diagnose_decision_gap.py
```

### D. Run Final Benchmark Evaluation on Held-Out Test Split
```bash
python scripts/run_final_test_evaluation.py
```

---

## 5. Repository Structure

```
recoverai/
├── data/
│   └── sim_v1/                 # Frozen benchmark dataset (Train: 7k, Val: 1.5k, Test: 1.5k)
├── docs/
│   ├── ARCHITECTURE.md         # Layer decoupling & observable boundary diagrams
│   ├── CAUSAL_MODEL.md         # Structural logit model & potential outcomes
│   ├── DECISIONS.md            # Architecture Decision Records (ADRs 001-008)
│   ├── EVALUATION.md           # Formal evaluation metrics & integer paise math
│   ├── ML_SYSTEM.md            # Machine learning decision theory & diagnostics
│   └── PRD.md                  # Product requirements & KPI definitions
├── ml/
│   ├── features.py             # Leakage-safe observable feature extraction (24D)
│   ├── dataset.py              # Supervised potential-outcome dataset bundles
│   ├── decision_engine.py      # Expected net value optimization & safety guardrails
│   ├── inference.py            # Production inference engine & explanation generator
│   └── models/
│       ├── base.py             # Abstract BaseRecoveryModel
│       ├── logistic_model.py   # Calibrated Logistic Regression model
│       ├── gbm_model.py        # Calibrated HistGradientBoosting model
│       └── bundle.py           # MultiActionRecoveryModel coordinator
├── reports/
│   ├── final_test_evaluation.json  # Reproducible test benchmark results
│   └── final_test_evaluation.md    # Markdown benchmark report
├── scripts/
│   ├── demo.py                 # Interactive scenario demonstration CLI
│   ├── diagnose_decision_gap.py# Decision gap diagnostic & confusion matrices
│   ├── run_final_test_evaluation.py # Test split evaluation runner
│   └── validation_decision_comparison.py # Validation comparison runner
├── simulator/                  # Frozen causal simulation environment (sim_v1)
└── tests/                      # 51 unit, integration, and security tests
```

---

## 6. Core Scientific & Engineering Principles

1. **Exact Financial Calculations (Integer Paise)**: All internal monetary quantities (`amount_paise`, `recovered_amount_paise`, `intervention_cost_paise`, `expected_net_paise`) are strictly 64-bit integers.
2. **Zero Ground-Truth Leakage Guarantee**: The inference path ingests only observable `PaymentCase` fields. Any unauthorized token (`latent_intent`, `latent_funds`, `optimal_action`, `actual_outcome`) immediately raises a `DataLeakageError`.
3. **Common Random Numbers (CRN)**: Policies are evaluated against identical realizations of potential outcomes $Y(a)$, guaranteeing that differences in net recovery represent true decision quality rather than stochastic noise.
4. **Customer-Level Split Partitioning**: Train (1,400 customers), Validation (300 customers), and Test (300 customers) are 100% disjoint at the customer identity level.