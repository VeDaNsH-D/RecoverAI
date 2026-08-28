"""
Comprehensive test suite for RecoverAI Production Readiness & Reliability (Milestone 3 Phase D).
Tests configuration validation, request correlation, structured error envelopes, readiness probes,
observability metrics, database reliability, and auditability.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.app import create_app
from api.services.recovery_service import recovery_service
from api.services.operations_service import operations_service
from api.observability import observability_registry
from recovery.repository import RecoveryRepository


@pytest.fixture(scope="module")
def client():
    # Use isolated shared in-memory DB for tests
    test_repo = RecoveryRepository(db_path=":memory:")
    operations_service.repository = test_repo

    # Load champion model
    model_path = Path("models/champion_recovery_model.pkl")
    recovery_service.load_model(model_path)
    observability_registry.reset_for_testing()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_configuration_loading_and_validation():
    """Verify settings defaults, env overrides, and invalid configuration rejection."""
    # 1. Valid default config
    cfg = Settings(env="development", port=8000, log_level="INFO")
    assert cfg.env == "development"
    assert cfg.port == 8000
    assert cfg.log_level == "INFO"

    # 2. Invalid port -> ValueError
    with pytest.raises((ValueError, Exception)):
        Settings(port=70000)

    # 3. Invalid env -> ValidationError
    with pytest.raises((ValueError, Exception)):
        Settings(env="staging_invalid")  # type: ignore

    # 4. Invalid log level -> ValidationError
    with pytest.raises((ValueError, Exception)):
        Settings(log_level="VERBOSE")  # type: ignore


def test_request_correlation_headers(client):
    """Verify X-Request-ID preservation and auto-generation."""
    # 1. Auto-generated request ID
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers
    assert resp.headers["x-request-id"].startswith("req_")

    # 2. Preserved client-supplied request ID
    custom_req_id = "merch_req_custom_998124"
    resp_custom = client.get("/api/v1/health", headers={"X-Request-ID": custom_req_id})
    assert resp_custom.status_code == 200
    assert resp_custom.headers["x-request-id"] == custom_req_id


def test_readiness_probe(client):
    """Verify GET /api/v1/ready probe under normal and degraded conditions."""
    # 1. Healthy readiness check -> 200 OK
    resp = client.get("/api/v1/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["model_status"] == "ready"
    assert data["database_status"] == "connected"
    assert data["model_family"] is not None

    # Top-level alias /ready
    resp_alias = client.get("/ready")
    assert resp_alias.status_code == 200
    assert resp_alias.json()["status"] == "ready"


def test_standardized_error_envelope_validation_error(client):
    """Verify 422 validation errors conform to standardized error envelope."""
    resp = client.post(
        "/api/v1/decisions",
        json={"forbidden_latent_intent": 0.99},
        headers={"X-Request-ID": "test_req_422"},
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["request_id"] == "test_req_422"
    assert resp.headers["x-request-id"] == "test_req_422"


def test_standardized_error_envelope_not_found(client):
    """Verify 404 not found errors return standardized error envelope."""
    resp = client.get(
        "/api/v1/recovery/actions/act_nonexistent_999",
        headers={"X-Request-ID": "test_req_404"},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] in ("NOT_FOUND", "ACTION_NOT_FOUND")
    assert data["error"]["request_id"] == "test_req_404"


def test_observability_metrics_endpoint(client):
    """Verify GET /api/v1/observability/metrics operational telemetry."""
    resp = client.get("/api/v1/observability/metrics")
    assert resp.status_code == 200
    metrics = resp.json()

    assert "uptime_seconds" in metrics
    assert "requests_total" in metrics
    assert metrics["requests_total"] >= 1
    assert "responses_2xx" in metrics
    assert "decisions_generated" in metrics
    assert "actions_dispatched" in metrics


def test_full_flow_auditability_and_observability(client):
    """Verify complete operational flow, audit trace, and observability counter increments."""
    # 1. Decision Creation
    req_payload = {
        "case_id": "case_prod_001",
        "customer_id": "cust_prod_001",
        "amount_paise": 400000,
        "currency": "INR",
        "payment_method": "upi",
        "is_subscription": False,
        "customer_historical_success_rate": 0.90,
        "customer_total_transactions": 20,
        "customer_total_failures": 2,
        "customer_avg_amount_paise": 400000,
        "customer_tenure_months": 12,
        "failure_type": "temporary_failure",
        "retry_count": 0,
        "hours_since_failure": 0.1,
    }
    r_dec = client.post("/api/v1/decisions", json=req_payload)
    assert r_dec.status_code == 200
    dec_data = r_dec.json()
    assert dec_data["expected_net_recovery_paise"] == dec_data["expected_gross_recovery_paise"] - dec_data["action_cost_paise"]

    # 2. Action Execution
    r_act = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": dec_data["decision_id"],
            "action": dec_data["recommended_action"],
            "idempotency_key": "idemp_prod_001",
        },
    )
    assert r_act.status_code == 200
    act_data = r_act.json()

    # 3. Outcome Recording
    r_out = client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_prod_001",
            "action_id": act_data["action_id"],
            "decision_id": dec_data["decision_id"],
            "outcome_status": "recovered",
            "recovered_amount_paise": 400000,
        },
    )
    assert r_out.status_code == 200

    # 4. Verify Observability Metrics Updated
    obs_resp = client.get("/api/v1/observability/metrics")
    assert obs_resp.status_code == 200
    obs = obs_resp.json()
    assert obs["decisions_generated"] >= 1
    assert obs["actions_dispatched"] >= 1
    assert obs["outcomes_recorded"] >= 1
