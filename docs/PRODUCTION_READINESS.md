# RecoverAI — Production Readiness & Reliability Guide

This document specifies the operational reliability, configuration, logging, request correlation, health probing, error handling, and auditability architecture for RecoverAI (Milestone 3 Phase D).

---

## 1. Architectural Overview

```
+-------------------------------------------------------------------------------+
|                             CLIENT / MERCHANT BACKEND                         |
|                                                                               |
|  - Sends HTTP Requests (Optional X-Request-ID header)                         |
|  - Ingests Standardized Error Responses (400, 404, 409, 422, 500, 503)        |
|  - Polls /api/v1/health (Liveness) & /api/v1/ready (Readiness)                |
|  - Queries /api/v1/observability/metrics (Traffic & Operational Counters)     |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                       RECOVERAI API MIDDLEWARE & ERROR LAYER                  |
|                                                                               |
|  1. RequestCorrelationMiddleware:                                             |
|     - Injects / Preserves X-Request-ID                                        |
|     - Structured JSON Access Logging (latency, status, path, method)          |
|     - Records in-memory traffic counters in ObservabilityRegistry             |
|                                                                               |
|  2. Centralized Global Exception Handlers:                                    |
|     - Converts Domain Exceptions to Standardized ErrorEnvelope                |
|     - Sanitizes 500 Internal Errors (hides tracebacks, preserves request_id)  |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                       DATABASE RELIABILITY & CONCURRENCY                      |
|                                                                               |
|  - SQLite WAL Mode + Foreign Keys (PRAGMA foreign_keys = ON)                  |
|  - Busy Timeout Protection (PRAGMA busy_timeout = 5000)                       |
|  - Persistence-Backed Atomic Idempotency via Unique Indices                   |
|  - Deterministic State Machine Transitions                                    |
+-------------------------------------------------------------------------------+
```

---

## 2. Environment Configuration

RecoverAI uses typed Pydantic configuration (`api/config.py`) loaded from environment variables with startup validation:

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `RECOVERAI_ENV` | `string` | `"development"` | Runtime environment: `"development"`, `"test"`, or `"production"` |
| `RECOVERAI_MODEL_PATH` | `string` | `"models/champion_recovery_model.pkl"` | File path to champion multi-action recovery model artifact |
| `RECOVERAI_DB_PATH` | `string` | `"data/recovery_operations.db"` | SQLite operational database file path |
| `RECOVERAI_HOST` | `string` | `"0.0.0.0"` | Network bind address |
| `RECOVERAI_PORT` | `integer` | `8000` | Network bind port ($1 \le \text{port} \le 65535$) |
| `RECOVERAI_LOG_LEVEL` | `string` | `"INFO"` | Logging verbosity: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"` |

---

## 3. Request Correlation & Structured Logging

### 3.1 `X-Request-ID` Header
Every HTTP interaction is tracked via a correlation identifier:
1. **Client Supplied**: If the client passes `X-Request-ID`, it is preserved.
2. **Auto Generated**: If missing or empty, the middleware generates a new `req_<uuid4_hex>` identifier.
3. **Response Propagation**: The correlation ID is always returned in the HTTP response header `X-Request-ID`.

### 3.2 Structured Access Logging
Access logs are emitted in JSON format via logger `recoverai.api.requests`:
```json
{
  "event": "http_request",
  "request_id": "req_123781e9cd1f4962ab1042b0da25ae9e",
  "method": "POST",
  "path": "/api/v1/decisions",
  "status_code": 200,
  "duration_ms": 6.45
}
```
> [!IMPORTANT]
> **Anti-Leakage Logging Rule**: Access and error logs never output customer secrets, latent variables, ground truth labels, or simulator unobservables.

---

## 4. Standardized Global Error Handling

All error responses return a standardized, predictable error envelope:

```json
{
  "error": {
    "code": "ACTION_MISMATCH",
    "message": "Requested action 'escalate' does not match recommended action 'retry'.",
    "request_id": "req_123781e9cd1f4962ab1042b0da25ae9e"
  },
  "timestamp": "2026-08-28T14:42:25.940477+00:00"
}
```

### Error Code Mapping:
- **`400 Bad Request`**: `ACTION_MISMATCH`, `ACTION_DISQUALIFIED`, `INVALID_OUTCOME_AMOUNT`, `CASE_REFERENCE_MISMATCH`
- **`404 Not Found`**: `NOT_FOUND`, `DECISION_NOT_FOUND`, `ACTION_NOT_FOUND`, `CASE_NOT_FOUND`
- **`409 Conflict`**: `IDEMPOTENCY_CONFLICT`, `INVALID_STATE_TRANSITION`, `DUPLICATE_OUTCOME`
- **`422 Unprocessable Entity`**: `VALIDATION_ERROR` (Strict schema rejection, unknown fields)
- **`503 Service Unavailable`**: `SERVICE_UNAVAILABLE` (Model artifact missing or DB offline)
- **`500 Internal Server Error`**: `INTERNAL_SERVER_ERROR` (Sanitized client message; full stack trace logged internally with `request_id`)

---

## 5. Health vs. Readiness Probes

### 5.1 Liveness Probe (`GET /api/v1/health`)
- Verifies that the FastAPI process is running.
- Backward compatible with Milestone 3 Phase A.
- Returns `200 OK` with `status: "healthy"` or `"degraded"`.

### 5.2 Deep Readiness Probe (`GET /api/v1/ready`)
- Verifies that all runtime dependencies are ready to serve merchant traffic:
  1. Champion Multi-Action Recovery Model loaded into memory.
  2. SQLite operational database connected and responsive (`SELECT 1`).
- Returns `200 OK` (`status: "ready"`) when operational.
- Returns `503 Service Unavailable` (`status: "not_ready"`) if any dependency fails.

---

## 6. Database Reliability & Concurrency

1. **Busy Timeout**: SQLite connection sets `PRAGMA busy_timeout = 5000;` to prevent lock contention under concurrent load.
2. **Atomic Idempotency**: Action idempotency is enforced by unique SQLite indices on `idempotency_key` and transactional state transitions, preventing duplicate dispatches across concurrent workers or server restarts.
3. **Transaction Safety**: All state updates (`DECIDED -> ACTION_PENDING -> ACTION_EXECUTED -> RECOVERED/NOT_RECOVERED`) run in atomic transaction blocks with automatic rollback on error.

---

## 7. Operational Observability (`GET /api/v1/observability/metrics`)

Exposes thread-safe in-memory runtime telemetry:
```json
{
  "uptime_seconds": 342.15,
  "requests_total": 1250,
  "responses_2xx": 1220,
  "responses_4xx": 28,
  "responses_5xx": 2,
  "avg_latency_ms": 4.82,
  "decisions_generated": 450,
  "actions_dispatched": 380,
  "execution_failures": 5,
  "outcomes_recorded": 375,
  "timestamp": "2026-08-28T14:45:00.000000+00:00"
}
```

---

## 8. Operational Limitations

> [!NOTE]
> **Scope & Boundaries**:
> - RecoverAI is currently an autonomous decision-support and local execution platform.
> - Direct payment gateway webhooks and merchant authentication/authorization (OAuth2/JWT) are planned for future integration milestones.
> - Operational analytics describe historical observations only and must not be used to claim counterfactual causal uplift.
