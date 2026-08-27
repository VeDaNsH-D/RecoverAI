# Product Requirements Document (PRD) — RecoverAI

## 1. Executive Summary

**Product Name**: RecoverAI  
**Hackathon Track**: Razorpay Buildathon — Track 03: AI Revenue Recovery  
**Tagline**: *Find revenue that's slipping away and win it back.*  

Failed payments represent a silent leak in business revenue: subscription renewals fail, one-time checkout authorizations get declined, network timeouts abort checkouts, and customer cards expire. Existing solutions use crude fixed retry intervals (e.g. retry after 24 hours, retry up to 4 times), which lead to high gateway fees, customer annoyance, and unrecovered revenue.

RecoverAI uses contextual AI to diagnose payment failure causes, compute expected recovery value across intervention choices, execute safe and policy-bounded recovery actions, and causally measure incremental recovered revenue.

---

## 2. Problem Statement & Economics

For digital businesses operating at scale:
1. **False Retries**: Retrying an `INVALID_PAYMENT_METHOD` or hard decline wastes gateway fees and risks merchant fraud flags.
2. **Customer Friction**: Blasting payment links or SMS reminders for transient network glitches annoys customers.
3. **Passive Inaction**: Failing to follow up on high-value `INSUFFICIENT_FUNDS` invoices leads to permanent churn.
4. **Lack of Incremental Measurement**: Merchants cannot distinguish between revenue that would have recovered on its own vs. revenue won back through active intervention.

---

## 3. Core Terminology & Domain Model

### 3.1 Failure Taxonomy

| Failure Type | Description | Primary Drivers | Synthetic Base Rate |
| :--- | :--- | :--- | :--- |
| `temporary_failure` | Transient network, bank switch, or gateway timeout. | Bank downtime, timeout, webhook delay | ~40% |
| `insufficient_funds` | Customer account lacks sufficient funds at transaction moment. | End-of-month cashflow, credit limit reached | ~30% |
| `invalid_payment_method` | Expired card, blocked card, invalid VPA / UPI handle. | Card expiration, revoked mandate | ~20% |
| `unknown_failure` | Unclassified bank error, risk rule trigger, anomaly. | Fraud block, bank security filter | ~10% |

### 3.2 Action Space

| Action | Description | Synthetic Friction Cost (Assumption) | Nominal Latency |
| :--- | :--- | :--- | :--- |
| `no_action` | Take no intervention. Let transaction expire or self-heal. | ₹0 (0 paise) | 0 hrs |
| `retry` | Automated server-to-server gateway retry. | ₹2.00 (200 paise) | ~0.5 hrs |
| `payment_link` | Generate & send dynamic Razorpay Payment Link (WhatsApp/SMS/Email). | ₹10.00 (1,000 paise) | ~4 hrs |
| `reminder` | Send notification to customer prompting account top-up or retry. | ₹5.00 (500 paise) | ~12 hrs |
| `escalate` | Escalate high-value / anomalous case to human finance/ops team. | ₹50.00 (5,000 paise) | ~24 hrs |

> *Note: Action costs and latencies are synthetic simulation benchmarks for calculating net economic return.*

---

## 4. Key Performance Indicators (KPIs)

### 4.1 Primary Metric
$$\Delta \text{Revenue} = \text{Net Revenue Recovered}_{\text{Policy}} - \text{Net Revenue Recovered}_{\text{Baseline}}$$
Where:
$$\text{Net Revenue Recovered} = \sum_{i \in \text{Recovered}} \text{Amount}_i - \sum_{j \in \text{Interventions}} \text{Cost}(a_j)$$

### 4.2 Secondary Metrics
- **Recovery Rate**: $\frac{\text{Cases Recovered}}{\text{Total Cases at Risk}}$
- **Intervention Rate**: $\frac{\text{Interventions Executed}}{\text{Total Cases at Risk}}$
- **Intervention Efficiency**: $\frac{\text{Successful Interventions}}{\text{Total Interventions}}$
- **Escalation Rate**: $\frac{\text{Escalations}}{\text{Total Cases at Risk}}$
- **Average Recovery Latency**: Mean hours to recover successful cases.
- **Action Distribution**: Percentage breakdown across the 5 actions.

---

## 5. Milestone Breakdown

- **Milestone 1: Simulation & Evaluation Foundation (Current)**
  - Synthetic data generation (2,000 customers, 10,000 cases).
  - Causal ground truth with Potential Outcomes ($Y(a)$) and Common Random Numbers.
  - Integer paise monetary handling.
  - Zero data leakage observable interfaces.
  - Deterministic Rule-Based Baseline Policy & Oracle Policy.
  - Evaluation engine & CLI tools.
- **Milestone 2: ML Uplift & Expected Value Models**
  - Feature engineering pipeline.
  - Conditional probability models $P(Y(a)=1 \mid X)$.
  - Expected Net Value maximization policy: $\arg\max_a (\hat{P}(a \mid X) \cdot \text{Amount} - \text{Cost}(a))$.
- **Milestone 3: Agentic Policy & Safety Layer**
  - LLM-orchestrated recovery with safety boundaries, audit trail, and explainability.
- **Milestone 4: Razorpay Integration & Dashboard**
  - Webhook listener for payment failures.
  - Real-time tool execution via Razorpay Test APIs.
  - Live revenue recovery dashboard.
