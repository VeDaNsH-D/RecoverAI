# RecoverAI — Recovery Operations Architecture & Lifecycle Guide

The **RecoverAI Recovery Operations Layer** transforms mathematical recovery decisions into a stateful, auditable, provider-agnostic recovery workflow with idempotent action execution and observed outcome tracking.

---

## 1. End-to-End Operational Workflow

```
FAILED PAYMENT INCIDENT
         ↓
POST /api/v1/decisions (Inference & Decision Engine)
         ↓
    [DECIDED] (Persisted Decision & Initialized Case)
         ↓
POST /api/v1/recovery/actions (Action Execution Dispatch)
         ↓
    [ACTION_PENDING]
         ↓
  +---------------+---------------+
  | (Success)                     | (Technical Failure)
  v                               v
[ACTION_EXECUTED]           [EXECUTION_FAILED]
  |                               |
  |                               +---> (Retry same action allowed)
  ↓
POST /api/v1/recovery/outcomes (Observed Settlement / Webhook)
  ↓
+-----------------+-----------------+
|                                   |
v                                   v
[RECOVERED]                  [NOT_RECOVERED]
(Terminal State)             (Terminal State)
```

---

## 2. State Machine & Legal Lifecycle Transitions

### 2.1 State Definitions
- **`DECIDED`**: The decision engine has evaluated the observable payment context, selected the optimal action, and established the case.
- **`ACTION_PENDING`**: Action dispatch is underway.
- **`ACTION_EXECUTED`**: Downstream provider (or mock) confirmed successful execution.
- **`EXECUTION_FAILED`**: Technical communication or provider error occurred during action dispatch.
- **`RECOVERED`**: Terminal outcome confirming payment was successfully recovered ($Y_{\text{obs}} = 1$).
- **`NOT_RECOVERED`**: Terminal outcome confirming recovery was not achieved ($Y_{\text{obs}} = 0$).

### 2.2 Legal State Transition Graph
```
DECIDED           → ACTION_PENDING
ACTION_PENDING    → ACTION_EXECUTED | EXECUTION_FAILED
EXECUTION_FAILED  → ACTION_PENDING (Retry of same action allowed)
ACTION_EXECUTED   → RECOVERED | NOT_RECOVERED
RECOVERED         → [TERMINAL]
NOT_RECOVERED     → [TERMINAL]
```

### 2.3 Critical Operational Distinction: `EXECUTION_FAILED` vs. `NOT_RECOVERED`
- **`EXECUTION_FAILED`** is an **infrastructure/technical error** during the attempt to dispatch an action (e.g. gateway timeout, SMS provider downtime, Zendesk API error). The recovery attempt has not completed, and the merchant may safely retry the *same* action.
- **`NOT_RECOVERED`** is a **business/operational outcome** where the action was successfully executed (e.g. payment link was delivered and viewed), but the customer did not pay before link expiration. This is a terminal state.

---

## 3. Provider-Agnostic Action Execution Layer

The action layer abstracts downstream communication and gateway providers. It never chooses an action; it strictly executes the action selected by the decision engine.

### Implemented Providers (`recovery/actions/`):
1. **`RetryActionProvider`** (`RecoveryAction.RETRY` | Cost: ₹2.00 / 200 paise): Automated server-side network retry against the payment gateway.
2. **`PaymentLinkActionProvider`** (`RecoveryAction.PAYMENT_LINK` | Cost: ₹10.00 / 1,000 paise): Generates a secure SMS/WhatsApp payment link.
3. **`ReminderActionProvider`** (`RecoveryAction.REMINDER` | Cost: ₹5.00 / 500 paise): Sends a notification or email reminder without a new invoice.
4. **`EscalateActionProvider`** (`RecoveryAction.ESCALATE` | Cost: ₹50.00 / 5,000 paise): Creates a high-priority support operations ticket for human outreach.
5. **`NoActionProvider`** (`RecoveryAction.NO_ACTION` | Cost: ₹0.00 / 0 paise): Passive observation strategy for negative-EV or micro-tickets.

---

## 4. Idempotency Guarantees

Every action execution request requires an `idempotency_key` (minimum 8 characters).

### Semantics:
1. **Same Idempotency Key + Same Payload**: Returns the existing `ActionExecutionResponse` deterministically with HTTP `200 OK` without re-dispatching to the provider.
2. **Same Idempotency Key + Different Payload**: Rejects with HTTP `409 Conflict` (`IdempotencyConflictError`).

---

## 5. Persistence & Schema Design

RecoverAI uses an atomic SQLite persistence architecture (`data/recovery_operations.db`):

```sql
-- Cases table tracking lifecycle
CREATE TABLE cases (
    case_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    amount_paise INTEGER NOT NULL,
    current_state TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    last_action_id TEXT,
    last_action_status TEXT,
    outcome_status TEXT,
    recovered_amount_paise INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Historical decision records
CREATE TABLE decisions (
    decision_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    amount_paise INTEGER NOT NULL,
    recommended_action TEXT NOT NULL,
    recommended_action_recovery_probability REAL NOT NULL,
    expected_gross_recovery_paise INTEGER NOT NULL,
    action_cost_paise INTEGER NOT NULL,
    expected_net_recovery_paise INTEGER NOT NULL,
    decision_margin_paise INTEGER NOT NULL,
    explanation TEXT NOT NULL,
    model_family TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(case_id)
);

-- Action executions
CREATE TABLE actions (
    action_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    action TEXT NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    cost_paise INTEGER NOT NULL,
    provider_reference TEXT NOT NULL,
    error_message TEXT,
    executed_at TEXT NOT NULL,
    FOREIGN KEY (decision_id) REFERENCES decisions(decision_id),
    FOREIGN KEY (case_id) REFERENCES cases(case_id)
);

-- Observed operational outcome events
CREATE TABLE outcomes (
    event_id TEXT PRIMARY KEY,
    action_id TEXT UNIQUE NOT NULL,
    case_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    outcome_status TEXT NOT NULL,
    recovered_amount_paise INTEGER NOT NULL,
    provider_reference TEXT,
    metadata_json TEXT,
    event_timestamp TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (action_id) REFERENCES actions(action_id),
    FOREIGN KEY (decision_id) REFERENCES decisions(decision_id),
    FOREIGN KEY (case_id) REFERENCES cases(case_id)
);
```

---

## 6. Observational Analytics (`GET /api/v1/recovery/summary`)

Provides real-time merchant operations analytics:
- **Operational Counts**: `total_cases`, `decisions_made`, `actions_executed`, `execution_failures`, `recovered_cases`, `not_recovered_cases`, `recovery_rate`.
- **Financial Ledgers (Exact Integer Paise)**:
  - $\text{Gross Recovered Paise} = \sum_{\text{recovered}} \text{recovered\_amount\_paise}$
  - $\text{Total Action Cost Paise} = \sum_{\text{executed}} \text{cost\_paise}$
  - $\text{Net Recovered Paise} = \text{Gross Recovered} - \text{Total Action Cost}$
- **Action Breakdown**: Distributions, recovery rates, and costs per action category.

> **Scientific Boundary**: Summary analytics represent observational production records. They do not claim causal counterfactual uplift. Causal evaluation remains isolated to the benchmark evaluation engine.
