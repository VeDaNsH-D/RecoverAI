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

### 2.2 Deep Readiness Check (Phase D)
- **Endpoint**: `GET /api/v1/ready` (also aliased to `GET /ready`)
- **Description**: Deep readiness probe verifying champion model availability and database connectivity.
- **Response `200 OK`**:
  ```json
  {
    "status": "ready",
    "model_status": "ready",
    "database_status": "connected",
    "model_family": "calibrated_logistic_regression",
    "timestamp": "2026-08-28T14:42:25.940477+00:00"
  }
  ```

---

### 2.3 Model Capabilities & Metadata
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

### 2.8 Merchant Recovery Analytics Endpoints (Phase C)
Comprehensive observational reporting over historical recovery operations:

| Endpoint | Method | Query Parameters | Description |
| :--- | :--- | :--- | :--- |
| `GET /api/v1/analytics/overview` | `GET` | `start_date`, `end_date`, `action`, `failure_type`, `is_subscription`, `retry_count` | Complete operational KPIs and financial reconciliation |
| `GET /api/v1/analytics/actions` | `GET` | `start_date`, `end_date`, `failure_type`, `is_subscription`, `retry_count` | Action-level breakdown in deterministic order |
| `GET /api/v1/analytics/failure-types` | `GET` | `start_date`, `end_date`, `action`, `is_subscription`, `retry_count` | Diagnostic failure type breakdown |
| `GET /api/v1/analytics/retry-count` | `GET` | `start_date`, `end_date`, `action`, `failure_type`, `is_subscription` | Prior retry count breakdown |
| `GET /api/v1/analytics/subscriptions` | `GET` | `start_date`, `end_date`, `action`, `failure_type`, `retry_count` | Segment breakdown (`subscription` vs `one_off`) |
| `GET /api/v1/analytics/trends` | `GET` | `interval` (`daily`/`weekly`), `start_date`, `end_date`, `action`, `failure_type`, `is_subscription`, `retry_count` | Time-series trend bucketing |

Detailed documentation: [`docs/ANALYTICS.md`](ANALYTICS.md)

---

### 2.9 Operational Observability Telemetry (Phase D)
- **Endpoint**: `GET /api/v1/observability/metrics` (also aliased to `GET /observability/metrics`)
- **Description**: Exposes runtime traffic, response status codes, rolling latency, and execution counters.
- **Sample Response `200 OK`**:
```json
{
  "uptime_seconds": 124.5,
  "requests_total": 450,
  "responses_2xx": 442,
  "responses_4xx": 8,
  "responses_5xx": 0,
  "avg_latency_ms": 5.2,
  "decisions_generated": 150,
  "actions_dispatched": 120,
  "execution_failures": 2,
  "outcomes_recorded": 118,
  "timestamp": "2026-08-28T14:45:00.000000+00:00"
}
```

Detailed documentation: [`docs/PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md)

---

### 2.10 Autonomous & LLM Tool-Calling Agent Endpoints (Milestones 4 & 5)
- **Endpoint**: `POST /api/v1/agent/recover`
- **Description**: Orchestrates an autonomous recovery workflow for a failed payment incident using Deterministic or LLM Tool-Calling drivers.
- **Request Body**:
```json
{
  "case_id": "case_agent_001",
  "customer_id": "cust_agent_001",
  "amount_paise": 750000,
  "currency": "INR",
  "payment_method": "upi",
  "is_subscription": false,
  "customer_historical_success_rate": 0.95,
  "customer_total_transactions": 40,
  "customer_total_failures": 1,
  "customer_avg_amount_paise": 750000,
  "customer_tenure_months": 20,
  "failure_type": "temporary_failure",
  "retry_count": 0,
  "hours_since_failure": 0.1,
  "driver": "llm",
  "idempotency_key": "idemp_agent_001"
}
```
- **Response `200 OK`**:
```json
{
  "agent_run_id": "run_d3ac95dbc8f5",
  "case_id": "case_agent_001",
  "decision_id": "dec_3faab210ea5c",
  "action_id": "act_09130f199ce3",
  "recommended_action": "retry",
  "executed_action": "retry",
  "execution_status": "EXECUTED",
  "final_operational_state": "ACTION_EXECUTED",
  "recovery_probability": 0.7064,
  "expected_gross_paise": 529767,
  "expected_gross_inr": 5297.67,
  "action_cost_paise": 200,
  "action_cost_inr": 2.0,
  "expected_net_paise": 529567,
  "expected_net_inr": 5295.67,
  "decision_margin_paise": 139125,
  "status": "completed",
  "driver_type": "llm",
  "total_tokens": 575,
  "llm_latency_ms": 10.0,
  "started_at": "2026-08-28T15:40:00.000000+00:00",
  "completed_at": "2026-08-28T15:40:00.050000+00:00",
  "trace": {
    "agent_run_id": "run_d3ac95dbc8f5",
    "case_id": "case_agent_001",
    "steps": [
      {
        "step_id": "step_1",
        "agent_run_id": "run_d3ac95dbc8f5",
        "step_index": 0,
        "step_type": "CASE_RETRIEVED",
        "status": "success"
      },
      {
        "step_id": "step_2",
        "agent_run_id": "run_d3ac95dbc8f5",
        "step_index": 1,
        "step_type": "DECISION_OBTAINED",
        "tool_name": "get_recovery_decision",
        "llm_prompt_tokens": 210,
        "llm_completion_tokens": 35,
        "status": "success"
      },
      {
        "step_id": "step_3",
        "agent_run_id": "run_d3ac95dbc8f5",
        "step_index": 2,
        "step_type": "ACTION_EXECUTED",
        "tool_name": "execute_recovery_action",
        "llm_prompt_tokens": 280,
        "llm_completion_tokens": 50,
        "status": "success"
      }
    ]
  }
}
```

- **Endpoint**: `GET /api/v1/agent/runs/{agent_run_id}`
- **Description**: Retrieves a persisted agent run and its full audit trace.

Detailed documentation: [`docs/AGENT_ARCHITECTURE.md`](AGENT_ARCHITECTURE.md) and [`docs/LLM_AGENT.md`](LLM_AGENT.md)

---

### 2.7 Razorpay Webhook Ingestion
- **Endpoint**: `POST /api/v1/webhooks/razorpay`
- **Description**: Ingests asynchronous Razorpay payment outcome notifications with HMAC-SHA256 signature verification and durable deduplication.
- **Headers**:
  - `X-Razorpay-Signature`: HMAC-SHA256 signature hex.
  - `X-Razorpay-Event-Id`: Unique event ID.
- **Supported Events**:
  - `payment_link.paid` $\to$ Settle case as `RECOVERED`.
  - `payment_link.expired` / `payment_link.cancelled` $\to$ Settle case as `NOT_RECOVERED`.

---

### 2.8 Razorpay Status Sync & Reconciliation
- **Endpoint**: `POST /api/v1/recovery/providers/razorpay/sync`
- **Description**: Actively queries Razorpay TEST API and reconciles case operational states.
- **Request Body**:
  ```json
  {
    "action_id": "act_09130f199ce3"
  }
  ```

Detailed documentation: [`docs/RAZORPAY_INTEGRATION.md`](RAZORPAY_INTEGRATION.md)

---

### 2.9 Subscription Recovery & Management
- **Endpoints**:
  - `GET /api/v1/recovery/subscriptions/{subscription_id}`: Retrieves subscription record, current billing cycle index, status, and associated recovery case.
  - `GET /api/v1/recovery/subscriptions?status={status}&limit={limit}`: Lists subscriptions with optional status filter (`active`, `pending`, `halted`, `cancelled`, `completed`).
  - `POST /api/v1/recovery/subscriptions/sync`: Actively synchronizes subscription status against Razorpay TEST API and reconciles associated open cases.
- **Request Body (`/sync`)**:
  ```json
  {
    "subscription_id": "sub_test_001"
  }
  ```
- **Response `200 OK`**:
  ```json
  {
    "subscription_id": "sub_test_001",
    "customer_id": "cust_001",
    "plan_id": "plan_monthly_pro",
    "status": "active",
    "current_cycle": 2,
    "total_cycles": 12,
    "amount_due_paise": 299900,
    "amount_due_inr": 2999.0,
    "currency": "INR",
    "charge_attempt_count": 0,
    "next_charge_at": null,
    "last_case_id": "sub_sub_test_001_inv_001",
    "is_recoverable": true,
    "created_at": "2026-09-05T00:00:00Z",
    "updated_at": "2026-09-05T00:00:00Z"
  }
  ```

Detailed documentation: [`docs/SUBSCRIPTION_RECOVERY.md`](SUBSCRIPTION_RECOVERY.md)

---

### 2.12 Merchant Recovery Command Center (Milestone 9)

- **Endpoints**:
  - `GET /api/v1/dashboard/overview`: Returns topline financial KPIs, 5-stage conversion funnel, and authoritative settlement attribution.
  - `GET /api/v1/recovery/cases`: Returns paginated, filterable case queue (`limit <= 100`, strict integer paise).
  - `GET /api/v1/recovery/cases/{case_id}`: Returns complete case detail separating Model Forecast from Settled Outcome.
  - `GET /api/v1/recovery/cases/{case_id}/timeline`: Returns strict chronological audit timeline of persisted events.
  - `GET /dashboard`: Serves the static single-page application.
  - `GET /`: 307 Redirect to `/dashboard`.

Detailed documentation: [`docs/DASHBOARD.md`](DASHBOARD.md)

---

## 3. Local Development Commands

### Start API Server:
```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
```

### Run Live Smoke Tests:
```bash
# Test API decisions
python scripts/smoke_test_api.py

# Test recovery operations lifecycle
python scripts/smoke_test_operations.py

# Test analytics & financial reconciliation
python scripts/smoke_test_analytics.py

# Test production readiness, correlation ID, and observability
python scripts/smoke_test_production_readiness.py

# Test deterministic recovery agent workflow & idempotency
python scripts/smoke_test_agent.py

# Test LLM tool-calling agent workflow & idempotency
python scripts/smoke_test_llm_agent.py

# Test Razorpay TEST MODE integration (Opt-in)
python scripts/smoke_test_razorpay.py
```

### Run Full Test Suite (124+ Tests):
```bash
python -m pytest tests/ -v
```
