# RecoverAI Merchant-Facing Recovery Decision & Operations API Reference

The RecoverAI API exposes real-time, economically bounded payment recovery decisioning and operations as a service for merchants, payment gateways, and subscription platforms.

---

## 1. Overview & Architecture

```
+-------------------------------------------------------------------------------+
|                           MERCHANT BACKEND / CLIENT                           |
|                                                                               |
|  1. POST /api/v1/decisions (PaymentCaseRequest)                               |
|  2. POST /api/v1/recovery/actions (ActionExecutionRequest)                    |
|  3. POST /api/v1/recovery/outcomes (OutcomeEventRequest)                      |
|  4. GET  /api/v1/recovery/summary (Analytics & Operational Ledger)            |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                       RECOVERAI API LAYER (FastAPI)                           |
|                                                                               |
|  - Closed/Strict Schema Validation (extra='forbid')                           |
|  - State Machine Enforcement & Idempotency Key Tracking                       |
|  - Separates Metadata (case_id, customer_id) from ML Observables              |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                       RECOVERY DECISION & OPERATIONS SERVICES                 |
|                                                                               |
|  - Ingests observable PaymentCase                                             |
|  - Invokes RecoverAIInferenceEngine (FeatureExtractor + Champion Models)      |
|  - Computes Expected Net Recovery in exact integer paise                      |
|  - Dispatches action execution to provider mocks (retry, plink, ops, etc.)    |
|  - Enforces Hard Safety Guardrails (Max Retries, Micro-Ticket Protection)     |
|  - Records observed settlement events atomically in SQLite                    |
+-------------------------------------------------------------------------------+
```

---

## 2. API Endpoints

### 2.1 Health Check
- **Endpoint**: `GET /api/v1/health` (also aliased to `GET /health`)
- **Description**: Returns operational status, model availability, and service version.
- **Response `200 OK`**:
  ```json
  {
    "status": "healthy",
    "service": "recoverai-decision-engine",
    "version": "0.1.0",
    "model_status": "ready",
    "model_family": "calibrated_logistic_regression",
    "timestamp": "2026-08-27T09:00:54.205838+00:00"
  }
  ```

---

### 2.2 Model Capabilities & Metadata
- **Endpoint**: `GET /api/v1/model-info`
- **Description**: Exposes product-safe metadata regarding the active champion recovery model.
- **Guarantees**: Zero internal coefficients, training labels, latent states, or ground truth are exposed.
- **Response `200 OK`**:
  ```json
  {
    "model_family": "calibrated_logistic_regression",
    "feature_version": "sim_v1_canonical_24d",
    "simulator_version": "sim_v1",
    "supported_actions": [
      "no_action",
      "retry",
      "payment_link",
      "reminder",
      "escalate"
    ],
    "feature_count": 24,
    "active_safety_guardrails": [
      "no_action_always_available",
      "max_retry_suppression (retry_count >= 2)",
      "micro_ticket_escalate_suppression (amount < INR 200)"
    ],
    "training_status": "trained_and_frozen",
    "disclaimer": "Inference operates strictly on observable payment context with zero access to unobservable customer parameters."
  }
  ```

---

### 2.3 Create Recovery Decision
- **Endpoint**: `POST /api/v1/decisions`
- **Description**: Evaluates an observable failed payment incident and produces the optimal bounded action recommendation with full auditable economics. Atomically persists the decision and establishes the case in `DECIDED` state.
- **Request Schema (`PaymentCaseRequest` - Closed Schema `extra='forbid'`):**

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `case_id` | `string` | Optional | Merchant transaction identifier (metadata only) |
| `customer_id` | `string` | Optional | Customer reference identifier (metadata only) |
| `merchant_id` | `string` | Optional | Merchant account ID (default: `"merch_recoverai_prod"`) |
| `created_at` | `string` | Optional | ISO 8601 incident timestamp |
| `amount_paise` | `integer` | **Required** | Transaction amount in integer paise ($\ge 0$) |
| `currency` | `string` | Optional | Currency code (default: `"INR"`) |
| `payment_method` | `string` | **Required** | `"upi"`, `"card"`, `"netbanking"`, `"mandate"` |
| `is_subscription` | `boolean`| Optional | Whether payment is a recurring SaaS/mandate charge |
| `customer_historical_success_rate` | `float` | **Required** | Lifetime historical success rate $[0.0, 1.0]$ |
| `customer_total_transactions` | `integer` | **Required** | Total prior transactions ($\ge 0$) |
| `customer_total_failures` | `integer` | **Required** | Total prior failed transactions ($\ge 0$) |
| `customer_avg_amount_paise` | `integer` | **Required** | Historical average ticket size in paise ($\ge 0$) |
| `customer_tenure_months` | `integer` | **Required** | Customer relationship tenure in months ($\ge 0$) |
| `failure_type` | `string` | **Required** | `"temporary_failure"`, `"insufficient_funds"`, `"invalid_payment_method"`, `"unknown_failure"` |
| `retry_count` | `integer` | Optional | Retries already attempted for this incident (default: $0$) |
| `hours_since_failure` | `float` | Optional | Elapsed hours since initial failure (default: $0.0$) |

#### Sample Request:
```bash
curl -X POST http://localhost:8000/api/v1/decisions \
  -H "Content-Type: application/json" \
  -d '{
    "case_id": "case_live_smoke_001",
    "customer_id": "cust_smoke_999",
    "amount_paise": 375000,
    "payment_method": "upi",
    "is_subscription": false,
    "customer_historical_success_rate": 0.94,
    "customer_total_transactions": 42,
    "customer_total_failures": 2,
    "customer_avg_amount_paise": 350000,
    "customer_tenure_months": 22,
    "failure_type": "temporary_failure",
    "retry_count": 0,
    "hours_since_failure": 0.25
  }'
```

#### Sample Response `200 OK`:
```json
{
  "decision_id": "dec_04495b4e5f1d",
  "case_id": "case_live_smoke_001",
  "recommended_action": "retry",
  "recommended_action_recovery_probability": 0.7219,
  "expected_gross_recovery_paise": 270704,
  "expected_gross_recovery_inr": 2707.04,
  "action_cost_paise": 200,
  "action_cost_inr": 2.0,
  "expected_net_recovery_paise": 270504,
  "expected_net_recovery_inr": 2705.04,
  "decision_margin_paise": 55321,
  "decision_margin_inr": 553.21,
  "explanation": "Recommend RETRY because it provides the highest expected net recovery of INR 2,705.04 (estimated 72.2% recovery rate) after an operational cost of INR 2.00. Fresh temporary technical failure detected with strong customer historical reliability; automated gateway retry is the most cost-effective recovery path. Decision margin: INR 553.21 over the next-best allowed alternative.",
  "safety_status": {
    "guardrails_applied": [
      "no_action_always_available"
    ],
    "retry_disqualified": false,
    "escalate_disqualified": false
  },
  "candidate_actions": [
    {
      "action": "no_action",
      "recovery_probability": 0.1732,
      "expected_gross_recovery_paise": 64935,
      "expected_gross_recovery_inr": 649.35,
      "action_cost_paise": 0,
      "action_cost_inr": 0.0,
      "expected_net_recovery_paise": 64935,
      "expected_net_recovery_inr": 649.35,
      "allowed": true,
      "disqualification_reason": null
    },
    {
      "action": "retry",
      "recovery_probability": 0.7219,
      "expected_gross_recovery_paise": 270704,
      "expected_gross_recovery_inr": 2707.04,
      "action_cost_paise": 200,
      "action_cost_inr": 2.0,
      "expected_net_recovery_paise": 270504,
      "expected_net_recovery_inr": 2705.04,
      "allowed": true,
      "disqualification_reason": null
    },
    {
      "action": "payment_link",
      "recovery_probability": 0.5765,
      "expected_gross_recovery_paise": 216183,
      "expected_gross_recovery_inr": 2161.83,
      "action_cost_paise": 1000,
      "action_cost_inr": 10.0,
      "expected_net_recovery_paise": 215183,
      "expected_net_recovery_inr": 2151.83,
      "allowed": true,
      "disqualification_reason": null
    },
    {
      "action": "reminder",
      "recovery_probability": 0.2622,
      "expected_gross_recovery_paise": 98339,
      "expected_gross_recovery_inr": 983.39,
      "action_cost_paise": 500,
      "action_cost_inr": 5.0,
      "expected_net_recovery_paise": 97839,
      "expected_net_recovery_inr": 978.39,
      "allowed": true,
      "disqualification_reason": null
    },
    {
      "action": "escalate",
      "recovery_probability": 0.4903,
      "expected_gross_recovery_paise": 183867,
      "expected_gross_recovery_inr": 1838.67,
      "action_cost_paise": 5000,
      "action_cost_inr": 50.0,
      "expected_net_recovery_paise": 178867,
      "expected_net_recovery_inr": 1788.67,
      "allowed": true,
      "disqualification_reason": null
    }
  ],
  "timestamp": "2026-08-27T09:00:55.030934+00:00"
}
```

---

### 2.4 Execute Recovery Action
- **Endpoint**: `POST /api/v1/recovery/actions`
- **Description**: Dispatches the recommended recovery action to the provider layer. Enforces strict idempotency.
- **Request Schema (`ActionExecutionRequest` - Closed Schema `extra='forbid'`):**

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `decision_id` | `string` | **Required** | Preceding decision identifier |
| `action` | `string` | **Required** | Action to execute (must match recommended action) |
| `idempotency_key` | `string` | **Required** | Merchant unique idempotency key ($\ge 8$ chars) |
| `merchant_reference` | `string` | Optional | Merchant transaction/audit reference |

#### Sample Request:
```bash
curl -X POST http://localhost:8000/api/v1/recovery/actions \
  -H "Content-Type: application/json" \
  -d '{
    "decision_id": "dec_04495b4e5f1d",
    "action": "retry",
    "idempotency_key": "idemp_order_991823_v1"
  }'
```

#### Sample Response `200 OK`:
```json
{
  "action_id": "act_d63b4a530e75",
  "decision_id": "dec_04495b4e5f1d",
  "case_id": "case_live_smoke_001",
  "action": "retry",
  "status": "EXECUTED",
  "provider_reference": "gw_retry_0e0398731c87",
  "cost_paise": 200,
  "cost_inr": 2.0,
  "error_message": null,
  "executed_at": "2026-08-27T09:23:51.120934+00:00",
  "idempotency_key": "idemp_order_991823_v1"
}
```

---

### 2.5 Get Action Details
- **Endpoint**: `GET /api/v1/recovery/actions/{action_id}`
- **Description**: Retrieves the status and provider reference of an executed action record.

---

### 2.6 Record Observed Outcome Event
- **Endpoint**: `POST /api/v1/recovery/outcomes`
- **Description**: Records an observed payment settlement or failure from a webhook or merchant ledger. Transitions the case to a terminal state (`RECOVERED` or `NOT_RECOVERED`).
- **Request Schema (`OutcomeEventRequest` - Closed Schema `extra='forbid'`):**

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `case_id` | `string` | **Required** | Associated case identifier |
| `action_id` | `string` | **Required** | Associated action execution ID |
| `decision_id` | `string` | **Required** | Associated decision ID |
| `outcome_status` | `string` | **Required** | `"recovered"` or `"not_recovered"` (NO `"failed"`!) |
| `recovered_amount_paise` | `integer` | **Required** | Amount recovered in integer paise ($> 0$ if recovered, $0$ if not) |
| `provider_reference` | `string` | Optional | External provider payment/settlement ID |
| `metadata` | `object` | Optional | Arbitrary key-value settlement metadata |
| `event_timestamp` | `string` | Optional | ISO 8601 timestamp of outcome |

#### Sample Request:
```bash
curl -X POST http://localhost:8000/api/v1/recovery/outcomes \
  -H "Content-Type: application/json" \
  -d '{
    "case_id": "case_live_smoke_001",
    "action_id": "act_d63b4a530e75",
    "decision_id": "dec_04495b4e5f1d",
    "outcome_status": "recovered",
    "recovered_amount_paise": 375000,
    "provider_reference": "pay_settlement_998124"
  }'
```

#### Sample Response `200 OK`:
```json
{
  "event_id": "evt_75c4bcdc924b",
  "case_id": "case_live_smoke_001",
  "action_id": "act_d63b4a530e75",
  "decision_id": "dec_04495b4e5f1d",
  "outcome_status": "recovered",
  "recovered_amount_paise": 375000,
  "recovered_amount_inr": 3750.0,
  "event_timestamp": "2026-08-27T09:23:51.150291+00:00",
  "created_at": "2026-08-27T09:23:51.150291+00:00"
}
```

---

### 2.7 Get Operational Recovery Summary
- **Endpoint**: `GET /api/v1/recovery/summary`
- **Description**: Returns observational operational and financial metrics across all persisted recovery cases.
- **Sample Response `200 OK`**:
```json
{
  "total_cases": 45,
  "decisions_made": 45,
  "actions_executed": 38,
  "execution_failures": 2,
  "recovered_cases": 28,
  "not_recovered_cases": 10,
  "recovery_rate": 0.7368,
  "gross_recovered_paise": 9850000,
  "gross_recovered_inr": 98500.0,
  "total_action_cost_paise": 48200,
  "total_action_cost_inr": 482.0,
  "net_recovered_paise": 9801800,
  "net_recovered_inr": 98018.0,
  "action_distribution": {
    "retry": 18,
    "payment_link": 14,
    "reminder": 4,
    "escalate": 2
  },
  "recovery_by_action": {
    "retry": {
      "action": "retry",
      "executed_count": 18,
      "recovered_count": 14,
      "recovery_rate": 0.7778,
      "gross_recovered_paise": 4500000,
      "gross_recovered_inr": 45000.0,
      "action_cost_paise": 3600,
      "action_cost_inr": 36.0,
      "net_recovered_paise": 4496400,
      "net_recovered_inr": 44964.0
    }
  },
  "execution_failures_by_action": {
    "payment_link": 2
  },
  "timestamp": "2026-08-27T09:25:00.000000+00:00"
}
```

---

## 3. Local Development Commands

### Start API Server:
```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
```

### Run Live Operations Smoke Test:
```bash
python scripts/smoke_test_operations.py
```

### Run Full Test Suite:
```bash
python -m pytest tests/ -v
```
