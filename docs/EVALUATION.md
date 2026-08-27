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

### 2.2 Secondary Metrics

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

8. **Average Recovery Latency**:
   $$\bar{L}(\pi) = \frac{\sum_{i=1}^N Y_i(a_i) \cdot \text{Latency}(a_i)}{\sum_{i=1}^N Y_i(a_i)}$$

9. **Action Distribution Breakdown**:
   Percentage breakdown of selected actions $\{a \in \mathcal{A}\}$.

---

## 3. Reference Policy Benchmarks

| Policy | Description | Ground Truth Access? | Role |
| :--- | :--- | :--- | :--- |
| **No Action** | Takes `no_action` on all cases. | NO | Lower bound / natural recovery baseline. |
| **Rule Baseline** | Deterministic heuristics (e.g. retry temporary failures, link for funds/cards, escalate unknown). | NO | Production reference benchmark to beat. |
| **Oracle** | Chooses $\arg\max_a (\mathbb{E}[\text{Net}](a))$ using true ground truth. | YES (Evaluator ONLY) | Theoretical performance ceiling. |
| **RecoverAI (Future ML/Agent)** | Chooses action maximizing predicted net expected value under safety bounds. | NO | Candidate policy being evaluated. |

---

## 4. Evaluation Workflow & Outputs

When running evaluation:
1. Evaluator loads observable cases and hidden ground truth.
2. Runs candidate policy (and baseline/oracle).
3. Evaluates all policies over the exact same potential outcomes ($Y(a)$).
4. Produces:
   - `evaluation_summary.json` (Structured metrics)
   - `case_results.csv` (Per-case decisions and outcomes)
   - Human-readable formatted console table.
