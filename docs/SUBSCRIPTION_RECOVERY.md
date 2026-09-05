# RecoverAI — Subscription Recovery Architecture & Specification

## 1. Executive Summary & Problem Context

In recurring SaaS and subscription-based commerce, **5–15% of recurring payment charges fail** due to:
- Expired credit/debit cards
- Mandate pre-debit notification or balance issues
- Temporary bank gateway downtime
- Customer balance insufficiency

Razorpay manages its own recurring billing lifecycle (`authenticated` $\to$ `active` $\to$ `pending` $\to$ `halted` $\to$ `cancelled` / `completed`) and automatically executes provider retries. Blanket retries or uninformed customer notifications increase gateway rejection fees, trigger payment fatigue, and cause involuntary churn.

**RecoverAI Subscription Recovery** extends RecoverAI into a **subscription-aware revenue recovery workflow** that:
1. Ingests authenticated Razorpay subscription lifecycle webhooks (`subscription.pending`, `subscription.charged`, `subscription.halted`, `subscription.activated`, `subscription.cancelled`, `subscription.completed`).
2. Isolates **Billing-Cycle Identity** to avoid conflating distinct recurring charges across monthly/annual cycles.
3. Passes normalized provider signals to the **authoritative `RecoveryDecisionEngine`** to determine the economically optimal bounded recovery action (`no_action`, `retry`, `payment_link`, `reminder`, `escalate`).
4. Enforces strict **Subscription Stopping Rules** to avoid illegal interventions on terminated subscriptions or customer spam.
5. Accurately attributes recovered revenue between **Provider Auto-Retry** and **RecoverAI Interventions** to prevent false claims and double counting.

---

## 2. Subscription Lifecycle & State Machine

```
                   [ Razorpay Subscription Ingress ]
                                   |
                  +----------------+----------------+
                  |                                 |
                  v                                 v
        [subscription.authenticated]       [subscription.activated]
        (Mandate Created / Verified)      (Subscription Active & Billing)
                  |                                 |
                  +----------------+----------------+
                                   |
                                   v
                        [ Periodic Charge Attempt ]
                                   |
                  +----------------+----------------+
                  |                                 |
                  v                                 v
        [ Charge Succeeded ]              [ Charge Failed ]
        [subscription.charged]            [subscription.pending]
                  |                                 |
                  |                       +---------+---------+
                  |                       | RecoverAI Ingress |
                  |                       | - Normalize retries
                  |                       | - Evaluate Engine
                  |                       | - Apply Stopping Rules
                  |                       | - Execute Action
                  |                       +---------+---------+
                  |                                 |
                  |              +------------------+------------------+
                  |              |                                     |
                  |              v (Retries Exhausted)                 v (Settled via Link)
                  |     [subscription.halted]                 [payment_link.paid]
                  |     - retry_count >= 2                    - Mark RECOVERED
                  |     - Explore Payment Link/Escalate       - Attribution: recoverai_intervention
                  |              |                                     |
                  +--------------+-------------------------------------+
                      [ Next Cycle / Completion ]
              [subscription.completed] / [subscription.cancelled]
              - Terminal state -> All interventions hard-stopped
```

### Retry Count Normalization & Safety Boundary
- `subscription.halted` normalizes the subscription's exhausted retry state to `PaymentCase.retry_count >= 2`, ensuring the existing retry safety boundary applies; it does not assume that Razorpay universally defines exhaustion as exactly two attempts.
- Ingested retry signals (`auth_attempts`, `notes.retry_count`, lifecycle events) are passed directly through the unified `RecoveryDecisionEngine`, preserving single-authority decision making.

---

## 3. Billing-Cycle Identity

Subscriptions persist across multiple monthly or annual cycles. A failure in Cycle 1 followed by recovery must **not** prevent a failure in Cycle 2 from being independently detected, evaluated, and recovered.

RecoverAI generates deterministic composite case identifiers:
$$\text{case\_id} = \text{derive\_billing\_cycle\_case\_id}(\text{subscription\_id}, \text{invoice\_id}, \text{cycle\_index}, \text{payment\_id})$$

- **Priority 1**: `sub_{subscription_id[:16]}_{invoice_id[:16]}`
- **Priority 2**: `sub_{subscription_id[:16]}_cyc{cycle_index}`
- **Priority 3**: `sub_{subscription_id[:16]}_{payment_id[:16]}`

---

## 4. Hard Deterministic Stopping Rules

Before any action is dispatched for a subscription failure, `evaluate_subscription_stopping_rules` evaluates six non-negotiable safety constraints:

1. **Terminal / Fail-Closed Subscription Guard**:
   If subscription status is `CANCELLED`, `COMPLETED`, or `UNKNOWN`, all interventions are prohibited. Unrecognized provider statuses fail closed.
2. **Terminal Case Guard**:
   If the recovery case is already in a terminal state (`RECOVERED` or `NOT_RECOVERED`), interventions are stopped.
3. **Single Intervention per Cycle Bound**:
   If an action was already executed (`ACTION_EXECUTED`), additional actions are blocked to prevent spamming the customer.
4. **Decision Engine `NO_ACTION` Respect**:
   If `RecoveryDecisionEngine` recommends `NO_ACTION`, no provider intervention is dispatched.
5. **Zero Amount Guard**:
   If `amount_due_paise <= 0`, no intervention is attempted.

---

## 5. Economic Attribution, Settlement Evidence & Anti-Double-Counting

To guarantee honest scientific reporting, eliminate false recovery claims, and prevent revenue inflation:

### Invariants:
1. **Subscription ACTIVE $\neq$ Billing Cycle RECOVERED**: Active subscription status alone is not proof of billing cycle settlement. Reconciliations require genuine settlement evidence for the specific matching invoice.
2. **$\text{ACTION\_EXECUTED}$ Preservation**:
   - $\text{ACTION\_EXECUTED} \xrightarrow{\text{matching invoice unpaid}} \text{Remain ACTION\_EXECUTED}$ (No revenue claimed)
   - $\text{ACTION\_EXECUTED} \xrightarrow{\text{matching invoice paid}} \text{RECOVERED}$ ($\text{recovered\_amount} = \text{invoice.amount\_paid}$)
3. **Authoritative Provider Money Rule**: Provider invoice/payment data is authoritative. `notes` metadata is never authoritative for financial calculations. For a paid invoice, recovered revenue is strictly `invoice.amount_paid`.
4. **Deterministic Attribution Proof**: RecoverAI attribution (`recoverai_intervention`) is claimed only with deterministic proof connecting the payment to the RecoverAI action (e.g. payment link payment ID match). Ambiguous sources default to `provider_auto_retry`.

| Resolution Mechanism | Attributed Source | Counted in RecoverAI Net Revenue? |
| :--- | :--- | :--- |
| Razorpay background auto-retry succeeds | `provider_auto_retry` | **No** (Descriptive gross recovery only) |
| Customer pays via RecoverAI Payment Link | `recoverai_intervention` | **Yes** ($\text{Gross} - \text{Action Cost}$) |
| Customer pays after RecoverAI Reminder/Escalation | `recoverai_intervention` | **Yes** ($\text{Gross} - \text{Action Cost}$) |
| Ambiguous settlement source | `provider_auto_retry` | **No** |
| Subscription cancelled/expired | `not_resolved` | **No** |

All financial arithmetic is computed in **64-bit integer paise** (1 INR = 100 paise).

---

## 6. API Contracts & Tooling

### Webhook Ingestion
- `POST /api/v1/webhooks/razorpay`:
  Ingests raw HMAC-SHA256 authenticated webhook events for both one-off payments and subscription lifecycles.

### Subscription API Endpoints
- `GET /api/v1/recovery/subscriptions/{subscription_id}`: Fetch subscription domain record.
- `GET /api/v1/recovery/subscriptions`: List subscriptions with status filter.
- `POST /api/v1/recovery/subscriptions/sync`: Actively synchronize state from Razorpay TEST API and reconcile open cases.

### Agent Orchestrator Tooling
- `sync_subscription`: Tool for autonomous recovery agents to query external Razorpay subscription status and trigger state reconciliation.
