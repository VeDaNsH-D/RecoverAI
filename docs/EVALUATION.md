# Evaluation & Benchmark Framework — RecoverAI

## 1. Core Evaluation Philosophy

The goal of RecoverAI is to maximize **Incremental Net Revenue Recovered** while minimizing unnecessary customer friction and operational costs.

Model metrics like accuracy, AUC-ROC, or precision are insufficient because:
1. They treat all transaction amounts equally (recovering a ₹50,000 transaction is worth 100x recovering a ₹500 transaction).
2. They ignore intervention costs (e.g. human escalation costs vs server-side automated retry).
3. They ignore counterfactual recovery (revenue that would have recovered anyway vs revenue won by intervention).

---

## 2. Formal Metric Definitions

Let $\mathcal{D} = \{(X_i, \mathbf{Y}_i, \text{Amount}_i)\}_{i=1}^N$ be the evaluation dataset of $N$ payment cases.
For a policy $\pi$, let $a_i = \pi(X_i) \in \mathcal{A}$ be the chosen action for case $i$.

### 2.1 Primary Metric: Incremental Net Revenue Recovered ($\Delta \text{Net Revenue}$)

$$\text{Net Revenue}(\pi) = \sum_{i=1}^N \left( Y_i(a_i) \cdot \text{Amount}_i - \text{Cost}(a_i) \right)$$

$$\Delta \text{Net Revenue}(\pi \text{ vs Baseline}) = \text{Net Revenue}(\pi) - \text{Net Revenue}(\pi_{\text{baseline}})$$

Where:
- $\text{Amount}_i$: Transaction value in integer paise.
- $Y_i(a_i) \in \{0, 1\}$: Potential outcome of action $a_i$ on case $i$.
- $\text{Cost}(a_i)$: Synthetic simulation friction cost in integer paise.

---

### 2.2 Decision-Quality & Regret Metrics

1. **Regret vs. Oracle**:
   $$\text{Regret}(\pi) = \text{Net Revenue}(\pi_{\text{oracle}}) - \text{Net Revenue}(\pi)$$

2. **Oracle Headroom Captured (%)**:
   $$\text{Headroom Captured}(\pi) = \frac{\text{Net Revenue}(\pi) - \text{Net Revenue}(\pi_{\text{baseline}})}{\text{Net Revenue}(\pi_{\text{oracle}}) - \text{Net Revenue}(\pi_{\text{baseline}})} \times 100\%$$

3. **Average Decision Margin (Paise / INR)**:
   $$\overline{\text{Margin}}(\pi) = \frac{1}{N} \sum_{i=1}^N \left( \hat{\mathbb{E}}[\text{Net}_i(a_i^*)] - \max_{a \neq a_i^*} \hat{\mathbb{E}}[\text{Net}_i(a)] \right)$$

---

### 2.3 Secondary Metrics

1. **Total Revenue at Risk**:
   $$\text{Rev}_{\text{risk}} = \sum_{i=1}^N \text{Amount}_i$$

2. **Total Gross Revenue Recovered**:
   $$\text{Rev}_{\text{gross}}(\pi) = \sum_{i=1}^N Y_i(a_i) \cdot \text{Amount}_i$$

3. **Gross Recovery Rate**:
   $$\text{Rate}_{\text{recovery}}(\pi) = \frac{\sum_{i=1}^N Y_i(a_i)}{N} \times 100\%$$

4. **Total Intervention Cost (Friction Cost)**:
   $$\text{Cost}_{\text{total}}(\pi) = \sum_{i=1}^N \text{Cost}(a_i)$$

5. **Intervention Rate**:
   $$\text{Rate}_{\text{intervention}}(\pi) = \frac{\sum_{i=1}^N \mathbb{I}(a_i \neq \text{no\_action})}{N} \times 100\%$$

6. **Intervention Success Rate (Efficiency)**:
   $$\text{Rate}_{\text{success}}(\pi) = \frac{\sum_{i=1}^N Y_i(a_i) \cdot \mathbb{I}(a_i \neq \text{no\_action})}{\sum_{i=1}^N \mathbb{I}(a_i \neq \text{no\_action})} \times 100\%$$

7. **Escalation Rate**:
   $$\text{Rate}_{\text{escalate}}(\pi) = \frac{\sum_{i=1}^N \mathbb{I}(a_i = \text{escalate})}{N} \times 100\%$$

---

## 3. Official Frozen Test Split Benchmark Results

- **Dataset**: `sim_v1` Held-Out Test Set (1,500 Cases, 300 Unseen Customers, **₹4,065,306.00 at Risk**)
- **Evaluation Mode**: Potential Outcomes under Common Random Numbers (CRN)

| Policy / Engine | Net Recovery (INR) | Gross Recovery (INR) | Cost (INR) | Delta vs Rule Baseline | Regret vs Oracle | Recovery Rate | Intervention Rate | Oracle Headroom Captured |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **No Action** | ₹66,517.00 | ₹66,517.00 | ₹0.00 | -₹2,638,788.00 (-97.54%) | ₹2,936,714.00 | 2.7% | 0.0% | -885.7% |
| **Rule Baseline** | ₹2,705,305.00 | ₹2,724,137.00 | ₹18,832.00 | -- | ₹297,926.00 | 69.2% | 100.0% | -- |
| **Logistic Decision Engine (Champion)** | **₹2,946,931.00** | **₹2,972,057.00** | **₹25,126.00** | **+₹241,626.00 (+8.93%)** | **₹56,300.00** | **71.3%** | **100.0%** | **81.1%** |
| **GBM Decision Engine** | ₹2,831,319.00 | ₹2,859,193.00 | ₹27,874.00 | +₹126,014.00 (+4.66%) | ₹171,912.00 | 69.6% | 100.0% | 42.3% |
| **Oracle (Benchmark Ceiling)** | ₹3,003,231.00 | ₹3,025,648.00 | ₹22,417.00 | +₹297,926.00 (+11.01%) | ₹0.00 | 72.9% | 88.5% | 100.0% |

---

## 4. Scale & Stress Evaluation (Milestone 7)

For high-throughput evaluation, latency/memory profiling, and customer-clustered bootstrap confidence intervals across large synthetic workloads (1,000 to 500,000+ cases), see:

👉 [**Scale Evaluation & Stress Testing Guide (`docs/SCALE_EVALUATION.md`)**](SCALE_EVALUATION.md)

