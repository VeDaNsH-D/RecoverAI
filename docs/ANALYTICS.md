# RecoverAI — Merchant Recovery Analytics & Observability Guide

The **RecoverAI Analytics & Observability Layer** provides descriptive, production-style reporting and aggregated ledgers over historical recovery decisions, action executions, outcomes, and operational costs.

---

## 1. Core Architectural & Scientific Principles

### 1.1 Strictly Observational (Zero Causal Claims)
> [!IMPORTANT]
> **Non-Negotiable Scientific Boundary**: All metrics exposed by the Analytics API are **descriptive and observational**. 
> They reflect what was observed in historical records. They **do NOT** represent causal uplift, treatment effects, counterfactual performance, or incremental revenue caused by RecoverAI. Causal evaluation remains strictly isolated to the frozen potential-outcomes simulator benchmark (`sim_v1`).

### 1.2 Exact Financial Calculations (Integer Paise)
All financial aggregates are computed using 64-bit integer arithmetic:
$$\text{Net Recovered Paise} = \text{Gross Recovered Paise} - \text{Total Action Cost Paise}$$
Floating-point values (`gross_recovered_inr`, `action_cost_inr`, `net_recovered_inr`) are generated solely for display purposes (`paise / 100.0`).

### 1.3 Critical Distinction: `EXECUTION_FAILED` vs `NOT_RECOVERED`
- **`EXECUTION_FAILED`**: The action dispatch encountered a **technical provider error** (e.g. gateway timeout, webhook failure). It is counted as an execution failure, incurs zero action cost, and may be retried.
- **`NOT_RECOVERED`**: The action was successfully executed by the provider, but the customer **did not pay** before expiration. This is a terminal business outcome contributing zero recovered revenue.

---

## 2. Analytics Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/analytics/overview` | `GET` | High-level operational and financial KPIs |
| `/api/v1/analytics/actions` | `GET` | Observational metrics grouped by recovery action |
| `/api/v1/analytics/failure-types` | `GET` | Observational recovery metrics grouped by failure type |
| `/api/v1/analytics/retry-count` | `GET` | Observational metrics grouped by prior retry count |
| `/api/v1/analytics/subscriptions` | `GET` | Observational metrics grouped by payment segment (subscription vs one-off) |
| `/api/v1/analytics/trends` | `GET` | Time-series metrics bucketed daily or weekly |
| `/api/v1/recovery/summary` | `GET` | Backward-compatible operational summary ledger |

---

## 3. Metric Definitions

### 3.1 Operational Rates
- **Observed Recovery Rate**:
  $$\text{Recovery Rate} = \frac{\text{Recovered Cases}}{\text{Recovered Cases} + \text{Not Recovered Cases}}$$
  *(Pending cases in `DECIDED`, `ACTION_PENDING`, or `ACTION_EXECUTED` awaiting resolution are excluded from the denominator)*.

- **Execution Success Rate**:
  $$\text{Execution Success Rate} = \frac{\text{Successful Executions}}{\text{Execution Attempts}}$$

- **Execution Failure Rate**:
  $$\text{Execution Failure Rate} = \frac{\text{Execution Failures}}{\text{Execution Attempts}}$$

### 3.2 Financial Totals
- **Gross Recovered Paise**:
  $$\text{Gross Recovered} = \sum_{o \in \text{Recovered Outcomes}} o.\text{recovered\_amount\_paise}$$

- **Total Action Cost Paise**:
  $$\text{Total Action Cost} = \sum_{a \in \text{Executed Actions}} a.\text{cost\_paise}$$

- **Net Recovered Paise**:
  $$\text{Net Recovered} = \text{Gross Recovered} - \text{Total Action Cost}$$

---

## 4. Query Filtering & Time-Series Semantics

All analytics endpoints accept standard query filters:
- `start_date` (ISO 8601 string, e.g. `2026-08-01`)
- `end_date` (ISO 8601 string, e.g. `2026-08-31`)
- `action` (`no_action`, `retry`, `payment_link`, `reminder`, `escalate`)
- `failure_type` (`insufficient_funds`, `invalid_payment_method`, `temporary_failure`, `unknown_failure`)
- `is_subscription` (`true`, `false`)
- `retry_count` (integer $\ge 0$)

### Time-Series Bucketing (`/api/v1/analytics/trends`):
- `interval=daily` (default): Groups by calendar date `YYYY-MM-DD`.
- `interval=weekly`: Groups by calendar week `YYYY-Www`.
- **Timestamp Specification**: Case creation date (`created_at`) is used as the primary indexing timestamp for bucket assignments.

---

## 5. Distinction: Predicted vs. Observed Metrics

| Dimension | Predicted (Decision Time) | Observed (Settlement Time) |
| :--- | :--- | :--- |
| **Recovery Rate** | $\hat{P}(Y(a)=1 \mid X)$ (Calibrated Probability) | Observed Settlements / Total Resolved |
| **Gross Yield** | $\lfloor \hat{P} \cdot \text{amount\_paise} \rfloor$ (Expected Gross) | Actual paise settled via gateway/webhook |
| **Cost** | Fixed operational cost policy | Actual fees incurred on executed actions |
| **Net Yield** | Expected Net Recovery ($\mathbb{E}[\text{Net}]$) | Actual Net Yield ($\text{Gross}_{\text{obs}} - \text{Cost}_{\text{obs}}$) |

---

## 6. Sample API Responses

### `GET /api/v1/analytics/overview`
```json
{
  "total_cases": 120,
  "decisions_made": 120,
  "actions_attempted": 110,
  "actions_executed": 105,
  "execution_failures": 5,
  "recovered_cases": 78,
  "not_recovered_cases": 27,
  "pending_cases": 15,
  "recovery_rate": 0.742857,
  "execution_success_rate": 0.954545,
  "execution_failure_rate": 0.045455,
  "total_amount_at_risk_paise": 34500000,
  "total_amount_at_risk_inr": 345000.0,
  "gross_recovered_paise": 24800000,
  "gross_recovered_inr": 248000.0,
  "total_action_cost_paise": 95200,
  "total_action_cost_inr": 952.0,
  "net_recovered_paise": 24704800,
  "net_recovered_inr": 247048.0,
  "timestamp": "2026-08-28T03:30:00.000000+00:00"
}
```

### `GET /api/v1/analytics/actions`
```json
[
  {
    "action": "no_action",
    "decisions": 10,
    "execution_attempts": 10,
    "successful_executions": 10,
    "execution_failures": 0,
    "recovered_cases": 1,
    "not_recovered_cases": 9,
    "recovery_rate": 0.1,
    "gross_recovered_paise": 50000,
    "gross_recovered_inr": 500.0,
    "action_cost_paise": 0,
    "action_cost_inr": 0.0,
    "net_recovered_paise": 50000,
    "net_recovered_inr": 500.0,
    "average_recovered_amount_paise": 50000,
    "average_recovered_amount_inr": 500.0
  },
  {
    "action": "retry",
    "decisions": 65,
    "execution_attempts": 65,
    "successful_executions": 65,
    "execution_failures": 0,
    "recovered_cases": 52,
    "not_recovered_cases": 13,
    "recovery_rate": 0.8,
    "gross_recovered_paise": 16500000,
    "gross_recovered_inr": 165000.0,
    "action_cost_paise": 13000,
    "action_cost_inr": 130.0,
    "net_recovered_paise": 16487000,
    "net_recovered_inr": 164870.0,
    "average_recovered_amount_paise": 317307,
    "average_recovered_amount_inr": 3173.07
  }
]
```
