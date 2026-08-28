# RecoverAI — Razorpay TEST MODE Integration Guide
## Milestone 6 Architecture, Security, and Operational Manual

---

## 1. Executive Summary & Core Principle

**RecoverAI Milestone 6** integrates **Razorpay TEST MODE** (`https://api.razorpay.com/v1/`) as an external payment infrastructure provider adapter.

> **Non-Negotiable Architecture Invariant**:
> - **Decision Authority is [`RecoveryDecisionEngine`](file:///c:/Users/Vedansh/recoverai/ml/decision_engine.py)**: Razorpay never calculates probabilities, evaluates expected net values, or chooses recovery actions.
> - **Workflow Authority is the Operations & State Machine Layer**: The application-level state machine and SQLite ledger remain authoritative for case state transitions.
> - **Razorpay is an Infrastructure Execution Adapter**: It receives approved, decided actions from [`ActionExecutor`](file:///c:/Users/Vedansh/recoverai/recovery/executor.py) and executes test payment operations.
> - **Offline Determinism by Default**: The system operates with `mock` providers by default. 100% of unit and integration tests run offline without external API keys. Live Razorpay API calls are strictly opt-in.
> - **Zero Real Customer Money Moved**: This integration operates strictly against Razorpay TEST MODE.

---

## 2. Architecture & Flow

```
                            +-------------------------------------------------------+
                            |              MERCHANT PAYMENT CASE INGESTION          |
                            +---------------------------+---------------------------+
                                                        |
                                                        v
                            +-------------------------------------------------------+
                            |          FeatureExtractor (24D Observable)            |
                            +---------------------------+---------------------------+
                                                        |
                                                        v
                            +-------------------------------------------------------+
                            |         RecoveryDecisionEngine (Authoritative)        |
                            |   - Evaluates: ENR(a) = P_rec * Amount - Cost         |
                            |   - Enforces safety boundaries (retry cap, micro-tick)|
                            +---------------------------+---------------------------+
                                                        |
                                                        v
                            +-------------------------------------------------------+
                            |           Recovery Operations & State Machine         |
                            |   - State: DECIDED -> ACTION_PENDING                  |
                            |   - Enforces action-match guardrail                   |
                            |   - Persists action record & idempotency key          |
                            +---------------------------+---------------------------+
                                                        |
                                                        v
                            +-------------------------------------------------------+
                            |            ActionExecutor & Provider Registry         |
                            +---------------------------+---------------------------+
                                                        |
                    +-----------------------------------+-----------------------------------+
                    | (if RECOVERAI_PAYMENT_PROVIDER="mock") | (if RECOVERAI_PAYMENT_PROVIDER="razorpay_test")
                    v                                       v
      +-----------------------------+         +-----------------------------------------------+
      |  PaymentLinkActionProvider  |         |   RazorpayPaymentLinkProvider (Adapter)       |
      |  (In-Memory Mock)           |         |   - Enforces rzp_test_ Key Prefix Guardrail   |
      +-----------------------------+         |   - Exact Integer Paise Amount Serialization  |
                                              |   - Maps reference_id & idempotency           |
                                              +-----------------------+-----------------------+
                                                                      |
                                                                      v
                                              +-----------------------------------------------+
                                              |          Razorpay TEST MODE REST API          |
                                              |         (POST /v1/payment_links)              |
                                              +-----------------------+-----------------------+
                                                                      |
                                              +-----------------------+-----------------------+
                                              |                                               |
                                              v (Async Push)                                  v (Active Pull)
                               +-----------------------------+                 +-----------------------------+
                               | POST /api/v1/webhooks/razorpay|               | POST /api/v1/recovery/...   |
                               | (HMAC-SHA256 Raw Bytes Val) |                 | .../providers/razorpay/sync |
                               +--------------+--------------+                 +--------------+--------------+
                                              |                                               |
                                              +-----------------------+-----------------------+
                                                                      |
                                                                      v
                                              +-----------------------------------------------+
                                              |      Record Outcome: RECOVERED / NOT_RECOVERED|
                                              |         (Integer Paise Financial Ledger)      |
                                              +-----------------------------------------------+
```

---

## 3. Action Mapping & Provider Boundary

| RecoverAI Action | Provider in `mock` mode | Provider in `razorpay_test` mode | Razorpay REST Endpoint | Lifecycle Semantics |
| :--- | :--- | :--- | :--- | :--- |
| **`payment_link`** | `PaymentLinkActionProvider` (Mock) | `RazorpayPaymentLinkProvider` | `POST /v1/payment_links` | Generates official Razorpay test payment link (`plink_xxx`). Captures short URL `https://rzp.io/i/xxx`. Sets state to `ACTION_EXECUTED`. Cost = 1000 paise (₹10.00). |
| **`retry`** | `RetryActionProvider` (Mock) | `RetryActionProvider` (Mock) | *None* | Gateway retry simulation. One-off UPI/card retries cannot be forced without recurring mandate tokens (Milestone 9). |
| **`reminder`** | `ReminderActionProvider` (Mock) | `ReminderActionProvider` (Mock) | *None* | Omnichannel customer notification simulation. |
| **`escalate`** | `EscalateActionProvider` (Mock) | `EscalateActionProvider` (Mock) | *None* | Merchant CRM / human support queue routing. |
| **`no_action`** | `NoActionProvider` (Mock) | `NoActionProvider` (Mock) | *None* | Passive observation. Cost = 0 paise. |

---

## 4. Configuration & Environment Variables

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `RECOVERAI_PAYMENT_PROVIDER` | string | `"mock"` | Provider selection: `"mock"` or `"razorpay_test"`. |
| `RAZORPAY_KEY_ID` | string | `None` | Razorpay API Key ID. **Must start with `rzp_test_`**. |
| `RAZORPAY_KEY_SECRET` | string | `None` | Razorpay API Key Secret. |
| `RAZORPAY_BASE_URL` | string | `"https://api.razorpay.com/v1"` | Razorpay REST API base endpoint. |
| `RAZORPAY_TIMEOUT_SECONDS` | float | `10.0` | HTTP request timeout in seconds. |
| `RAZORPAY_WEBHOOK_SECRET` | string | `None` | Webhook HMAC secret for signature verification. |
| `RECOVERAI_ENABLE_RAZORPAY_SMOKE` | bool | `false` | Enables live external test-mode smoke test. |

---

## 5. Security & Test-Mode Key Guardrails

1. **Strict Key Prefix Guardrail**:
   - `RazorpayClient` validates that `key_id` strictly starts with `rzp_test_`.
   - If an `rzp_live_` key or unknown prefix is supplied, `RazorpayClient` immediately raises `SecurityConfigurationError` and aborts execution.
2. **Secret Redaction**:
   - `Authorization: Basic ...` headers, API keys, and webhook secrets are automatically scrubbed from logs, traces, exception strings, and API error responses (`rzp_test_***:***`).
3. **Anti-Leakage**:
   - Latent simulator fields ($Y(a)$, `latent_intent`, `latent_funds`) are strictly forbidden across observable API and provider boundaries.

---

## 6. Webhooks & Active Sync Reconciliation

### A. Webhook Ingestion (`POST /api/v1/webhooks/razorpay`)
- Verifies `X-Razorpay-Signature` using HMAC-SHA256 computed over raw request body bytes with `RAZORPAY_WEBHOOK_SECRET`.
- Performs durable deduplication via SQLite table `webhook_events`.
- Maps supported terminal events:
  - `payment_link.paid` $\to$ `RECOVERED` (`recovered_amount_paise = amount_paid`).
  - `payment_link.expired` / `payment_link.cancelled` $\to$ `NOT_RECOVERED` (`recovered_amount_paise = 0`).

### B. Active Sync Endpoint (`POST /api/v1/recovery/providers/razorpay/sync`)
- Actively polls `GET /v1/payment_links/{plink_id}` and reconciles case state into `RECOVERED` or `NOT_RECOVERED`.

---

## 7. State Machine Invariants

- `Payment Link Created != Payment Recovered`: Creating a link achieves `ACTION_EXECUTED`. Payment settlement achieves `RECOVERED`.
- `EXECUTION_FAILED != NOT_RECOVERED`: Technical network/gateway failures transition cases to `EXECUTION_FAILED` (Cost = 0 paise) and permit retries of the same action.

---

## 8. Running Smoke Tests

### Offline Tests (Default)
```bash
python -m pytest tests/test_razorpay_client.py tests/test_razorpay_provider.py tests/test_razorpay_webhook.py -v
```

### Live Opt-In TEST MODE Smoke Test
```bash
# Set test-mode credentials
export RECOVERAI_ENABLE_RAZORPAY_SMOKE=true
export RECOVERAI_PAYMENT_PROVIDER=razorpay_test
export RAZORPAY_KEY_ID=rzp_test_your_key_id
export RAZORPAY_KEY_SECRET=your_key_secret

python scripts/smoke_test_razorpay.py
```
