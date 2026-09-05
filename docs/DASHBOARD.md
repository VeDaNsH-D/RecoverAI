# RecoverAI — Merchant Recovery Command Center (Milestone 9)

## 1. Overview & Architecture

The **Merchant Recovery Command Center** is RecoverAI's merchant-facing observability and operational control surface. It exposes real-time recovery intelligence, bounded interventions, settlement reconciliation, subscription recovery, and chronological audit trails in an intuitive single-page application (SPA).

```
                      MERCHANT RECOVERY COMMAND CENTER
                                     │
           ┌─────────────────────────┼─────────────────────────┐
           │                         │                         │
     [Overview & Funnel]      [Recovery Queue]         [Subscriptions]
     - Topline KPIs           - Search & Filters       - Active Subscriptions
     - 5-Stage Funnel         - Paginated Queue (<=100)- Bounded Per-Sub Sync
     - Attribution Donut      - Case Detail Modal      - Confirmation Dialog
     - Action Yield Breakdown - Audit Timeline (DB)    - Status Indicators
           │                         │                         │
           └─────────────────────────┼─────────────────────────┘
                                     │ Async REST API (JSON)
                                     v
                       FASTAPI BACKEND ROUTING
                                     │
       ├── UI Static SPA & Redirects:
       │   ├── GET /                                -> 307 Redirect to /dashboard
       │   └── GET /dashboard                       -> Static SPA (HTML/JS/CSS)
       │
       └── API v1 Endpoints (prefix: /api/v1):
           ├── GET  /api/v1/dashboard/overview      -> Topline KPIs, Funnel, Attribution
           ├── GET  /api/v1/recovery/cases          -> Paginated & Filtered Case Queue
           ├── GET  /api/v1/recovery/cases/{id}     -> Full Case, Decision, Action, Outcome
           ├── GET  /api/v1/recovery/cases/{id}/timeline -> Persisted Chronological Audit Trail
           ├── POST /api/v1/recovery/subscriptions/sync -> Single-Subscription Reconciliation
           └── GET  /api/v1/analytics/*             -> Observational Trends & Breakdowns
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        v                            v                            v
[AnalyticsService]          [RecoveryRepository]       [ReconciliationService]
(Single Analytics Truth)    (Cases, Decisions,          (Authoritative Razorpay
                             Actions, Outcomes, Logs)    Settlement Evidence)
        └────────────────────────────┼────────────────────────────┘
                                     v
                           [SQLite Database / WAL]
```

---

## 2. Core Architectural & Financial Invariants

1. **Observability & Control Surface ONLY**:
   - The frontend is strictly an observational client and control trigger.
   - It never calculates recovery probabilities, expected net recovery, or makes autonomous decisions.
   - The authoritative decision maker is `RecoveryDecisionEngine`.
   - The authoritative state machine is `OperationsService`.
   - The authoritative settlement reconciliation is `reconciliation.py`.

2. **Single Source of Analytics Truth**:
   - Both `/api/v1/analytics/*` and `/api/v1/dashboard/*` endpoints reuse `AnalyticsService` and `AnalyticsRepository`.
   - No duplicate or drifting SQL calculations exist across different layers.

3. **Strict Integer Paise Financial Arithmetic**:
   - All monetary values are represented as integer paise; no floating-point monetary arithmetic is used.
   - No floating-point currency representations enter the case-level API schemas. The frontend formats paise into Indian Rupee strings (`formatPaiseINR(paise)`).

4. **Attribution Isolation Guarantee**:
   $$\text{RecoverAI Net Recovered} = \text{RecoverAI-Attributed Gross} - \text{Total Action Cost}$$
   - Provider auto-retry recoveries are partitioned into a separate gross bucket (`provider_gross_recovered_paise`) and are **never** credited toward RecoverAI Net Recovered.

5. **Forecast vs. Observed Separation**:
   - The Command Center explicitly distinguishes **Model Forecast Estimates** (predicted $P(Y(a)=1|X)$, expected gross yield, expected net yield from the decision ledger) from **Authoritative Settlement Outcomes** (actual settled amount from provider webhooks/reconciliation).

6. **Privacy & Data Safeguards**:
   - No personally identifiable customer information (names, emails, phone numbers, raw card/UPI tokens) is exposed in API contracts.
   - Synthetic customer IDs are masked in the UI (e.g. `cust_••••91A2`).
   - Zero provider API secrets or webhook signing secrets are transmitted to the browser.

7. **Strict Audit Timeline Integrity**:
   - Every event in `/api/v1/recovery/cases/{case_id}/timeline` corresponds strictly to a genuine persisted record in the database.
   - The system never synthesizes unpersisted events (e.g. no fake webhook events if none were received).

8. **Bounded Operational Control**:
   - Subscription reconciliation is performed on a targeted, per-subscription basis via `POST /api/v1/recovery/subscriptions/sync` with payload `{"subscription_id": "sub_xxx"}` and explicit confirmation dialog.

---

## 3. Command Center Features

### 3.1 Overview & Funnel
- **7 Topline KPI Cards**:
  - Revenue at Risk (Total ₹ at risk across open/settled cases)
  - RecoverAI Net Recovered (Attributed yield minus operational friction costs)
  - Provider Auto-Recovered (Isolated provider auto-retry gross)
  - Total Gross Recovered (Sum of all settled recoveries)
  - Action Friction Costs (Total cost of dispatched actions)
  - Recovery Rate (% of resolved cases recovered)
  - Active Queue (Open in-flight cases)
- **5-Stage Conversion Funnel**:
  1. `1. Cases at Risk` (`funnel.cases_at_risk`): Total failed payment incidents observed and evaluated.
  2. `2. Decisions Evaluated` (`funnel.decisions_evaluated`): Total cases where `RecoveryDecisionEngine` computed optimal action.
  3. `3. Interventions Dispatched` (`funnel.interventions_dispatched`): Total recovery action executions attempted.
  4. `4. Successful Executions` (`funnel.successful_executions`): Total actions executed without provider technical failure.
  5. `5. Recovered Outcomes` (`funnel.recovered_outcomes`): Total cases confirmed and settled as recovered.
- **Settlement Attribution Donut**:
  - Pure SVG visual breakdown of RecoverAI Interventions vs Provider Auto-Retries vs Unresolved / In-Flight.
- **Action Category Yield**:
  - Visual breakdown of recovery yield, decision count, and recovery rate across bounded actions (`retry`, `payment_link`, `reminder`, `escalate`, `no_action`).

### 3.2 Recovery Queue
- **Filter Toolbar**:
  - `limit`: int (1..100, default 20)
  - `offset`: int (ge=0, default 0)
  - `state`: CaseState filter (`DECIDED`, `ACTION_PENDING`, `ACTION_EXECUTED`, `RECOVERED`, `NOT_RECOVERED`, `EXECUTION_FAILED`)
  - `action`: RecoveryAction filter (`no_action`, `retry`, `payment_link`, `reminder`, `escalate`)
  - `failure_type`: FailureType filter (`insufficient_funds`, `invalid_payment_method`, `temporary_failure`, `unknown_failure`)
  - `is_subscription`: bool filter (`true` for subscriptions, `false` for one-off)
  - `retry_count`: int filter (ge=0)
  - `search`: string filter across `case_id` or `customer_id`
- **Paginated Data Table**: Bounded pagination (`limit <= 100`), status pills, masked customer IDs, and formatted currency.
- **View Detail Drawer**: Opens a 3-column comparative view and chronological audit timeline.

### 3.3 Subscriptions Tab
- **Registry Table**: Statuses (`active`, `halted`, `completed`, `cancelled`, `unknown`, `pending`), current billing cycle, amount due, charge attempts, recoverable status.
- **Per-Subscription Sync**: Explicit `[Sync & Reconcile]` button opening a confirmation modal to invoke authoritative invoice reconciliation.

### 3.4 Analytics & Trends Tab
- **Time-Series Recovery Trends**: Daily and weekly intervals displaying aggregated revenue volume and intervention counts.
- **Prior Retry Count Breakdown**: Recovery yields grouped by retry count ($0, 1, 2, \dots$).
- **Segment Breakdown**: Comparative yield between Recurring Subscriptions and One-Off Transactions.

---

## 4. API Endpoints Reference

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/api/v1/dashboard/overview` | High-level KPIs, 5-stage conversion funnel, and authoritative attribution breakdown. |
| `GET` | `/api/v1/recovery/cases` | Paginated queue of recovery cases with filtering and search (limit $\le 100$). |
| `GET` | `/api/v1/recovery/cases/{id}` | Full case detail separating Model Forecast from Settled Outcome. |
| `GET` | `/api/v1/recovery/cases/{id}/timeline` | Persisted chronological audit timeline. |
| `GET` | `/dashboard` | Serves the static Single-Page Application (HTML/JS/CSS). |
| `GET` | `/` | 307 Redirect to `/dashboard`. |

---

## 5. Running the Command Center

1. Start the API server:
   ```bash
   python -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
   ```
2. Open your web browser and navigate to:
   ```
   http://127.0.0.1:8000/dashboard
   ```
3. The dashboard will automatically connect to `/api/v1/*` endpoints and refresh live operational data.
