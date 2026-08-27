# RecoverAI Merchant-Facing Recovery Decision API Reference

The RecoverAI API exposes real-time, economically bounded payment recovery decisioning as a service for merchants, payment gateways, and subscription platforms.

---

## 1. Overview & Architecture

```
+-------------------------------------------------------------------------------+
|                           MERCHANT BACKEND / CLIENT                           |
|                                                                               |
|  POST /api/v1/decisions (PaymentCaseRequest)                                  |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                       RECOVERAI API LAYER (FastAPI)                           |
|                                                                               |
|  - Closed/Strict Schema Validation (extra='forbid')                           |
|  - Separates Metadata (case_id, customer_id) from ML Observables              |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                       RECOVERY DECISION SERVICE                               |
|                                                                               |
|  - Ingests observable PaymentCase                                             |
|  - Invokes RecoverAIInferenceEngine (FeatureExtractor + Champion Models)      |
|  - Computes Expected Net Recovery in exact integer paise                      |
|  - Enforces Hard Safety Guardrails (Max Retries, Micro-Ticket Protection)     |
|  - Formulates Merchant-Friendly Explanation                                   |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                      MERCHANT DECISION RESPONSE (JSON)                        |
|                                                                               |
|  - Recommended Action, Expected Net Value (INR & Paise), Decision Margin      |
|  - Full Candidate Actions Comparison Ledger & Safety Status                   |
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
- **Degraded Status (`model_status: "model_unavailable"`)**: Returned if the pre-trained champion model artifact cannot be found on disk.

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
- **Description**: Evaluates an observable failed payment incident and produces the optimal bounded action recommendation with full auditable economics.
- **Request Schema (`PaymentCaseRequest` - Strict Closed Schema `extra='forbid'`):**

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

## 3. Safety Guardrails & Policy Constraints

1. **`NO_ACTION` Safety Invariant**: `NO_ACTION` is always available across all payment requests. If all active interventions yield negative expected net value ($\mathbb{E}[\text{Net}](a) < 0$), the engine selects `NO_ACTION`.
2. **Retry Exhaustion Protection**: If `retry_count >= 2`, `RETRY` is disqualified (`allowed = false`, reason: `max_retries_exceeded: retry_count >= 2`).
3. **Micro-Ticket Protection**: If `amount_paise < 20,000` (₹200), `ESCALATE` is disqualified (`allowed = false`, reason: `micro_ticket_protection: amount < 20000 paise`) to prevent spending ₹50 fees on low-ticket items.

---

## 4. Model Loading & Lifecycle Safety

- **Startup Loading**: The API loads the pre-trained champion model artifact (`models/champion_recovery_model.pkl`) once on application startup.
- **No Per-Request Retraining**: Zero training overhead during API requests.
- **Model Artifact Generation**:
  ```bash
  python scripts/save_champion_model.py
  ```
  Generates `models/champion_recovery_model.pkl` (33.80 KB).
- **Graceful Degradation**: If the model artifact is missing or corrupted, `/health` reports `status: "degraded", model_status: "model_unavailable"`, and `/api/v1/decisions` returns `503 Service Unavailable`.

---

## 5. Local Development Commands

### Start API Server:
```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
```

### Run Live HTTP Smoke Test:
```bash
python scripts/smoke_test_api.py
```

### Run Full Test Suite:
```bash
python -m pytest tests/ -v
```
