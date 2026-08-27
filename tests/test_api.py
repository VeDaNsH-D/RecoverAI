"""
API test suite for RecoverAI Merchant-Facing Recovery Decision API.
Tests endpoints: /api/v1/health, /api/v1/model-info, /api/v1/decisions, safety guardrails,
strict schema validation (extra='forbid'), anti-leakage, and degraded model handling.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from simulator.config import RecoveryAction, FailureType, PaymentMethod
from api.app import create_app
from api.services.recovery_service import recovery_service


@pytest.fixture(scope="module")
def client():
    # Ensure champion model is loaded
    model_path = Path("models/champion_recovery_model.pkl")
    recovery_service.load_model(model_path)
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint_healthy(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["model_status"] == "ready"
    assert data["service"] == "recoverai-decision-engine"
    assert data["version"] == "0.1.0"
    assert "model_family" in data


def test_model_info_endpoint(client):
    response = client.get("/api/v1/model-info")
    assert response.status_code == 200
    data = response.json()
    assert data["model_family"] == "calibrated_logistic_regression"
    assert data["feature_version"] == "sim_v1_canonical_24d"
    assert data["simulator_version"] == "sim_v1"
    assert len(data["supported_actions"]) == 5
    assert data["feature_count"] == 24
    assert len(data["active_safety_guardrails"]) >= 3
    # Verify no hidden ground-truth or evaluation data is leaked
    for forbidden in ["ground_truth", "latent", "potential_outcomes", "oracle", "y_true"]:
        assert forbidden not in str(data).lower()


def test_valid_decision_request(client):
    payload = {
        "case_id": "case_api_test_001",
        "customer_id": "cust_api_test_001",
        "merchant_id": "merch_acme_corp",
        "amount_paise": 250000,  # ₹2,500.00
        "currency": "INR",
        "payment_method": "upi",
        "is_subscription": False,
        "customer_historical_success_rate": 0.88,
        "customer_total_transactions": 25,
        "customer_total_failures": 3,
        "customer_avg_amount_paise": 240000,
        "customer_tenure_months": 14,
        "failure_type": "temporary_failure",
        "retry_count": 0,
        "hours_since_failure": 0.5,
    }

    response = client.post("/api/v1/decisions", json=payload)
    assert response.status_code == 200
    data = response.json()

    # Verify decision structure
    assert data["case_id"] == "case_api_test_001"
    assert data["decision_id"].startswith("dec_")
    assert data["recommended_action"] in [a.value for a in RecoveryAction]
    assert 0.0 <= data["recommended_action_recovery_probability"] <= 1.0

    # Verify integer paise & INR fields
    assert data["expected_gross_recovery_paise"] >= 0
    assert data["expected_gross_recovery_inr"] == round(data["expected_gross_recovery_paise"] / 100.0, 2)
    assert data["action_cost_paise"] >= 0
    assert data["action_cost_inr"] == round(data["action_cost_paise"] / 100.0, 2)
    assert data["expected_net_recovery_paise"] == data["expected_gross_recovery_paise"] - data["action_cost_paise"]
    assert data["expected_net_recovery_inr"] == round(data["expected_net_recovery_paise"] / 100.0, 2)
    assert data["decision_margin_paise"] >= 0

    # Verify explanation & safety report
    assert len(data["explanation"]) > 20
    assert "safety_status" in data
    assert data["safety_status"]["retry_disqualified"] is False
    assert data["safety_status"]["escalate_disqualified"] is False

    # Verify candidate actions comparison ledger
    assert len(data["candidate_actions"]) == 5
    for cand in data["candidate_actions"]:
        assert cand["action"] in [a.value for a in RecoveryAction]
        assert 0.0 <= cand["recovery_probability"] <= 1.0
        assert cand["expected_gross_recovery_inr"] == round(cand["expected_gross_recovery_paise"] / 100.0, 2)
        assert cand["action_cost_inr"] == round(cand["action_cost_paise"] / 100.0, 2)
        assert cand["expected_net_recovery_paise"] == cand["expected_gross_recovery_paise"] - cand["action_cost_paise"]
        assert isinstance(cand["allowed"], bool)


def test_strict_schema_rejects_unknown_and_forbidden_fields(client):
    """Ensure that unknown fields (e.g. injected ground truth) are structurally rejected with 422."""
    valid_payload = {
        "amount_paise": 250000,
        "currency": "INR",
        "payment_method": "upi",
        "is_subscription": False,
        "customer_historical_success_rate": 0.88,
        "customer_total_transactions": 25,
        "customer_total_failures": 3,
        "customer_avg_amount_paise": 240000,
        "customer_tenure_months": 14,
        "failure_type": "temporary_failure",
        "retry_count": 0,
        "hours_since_failure": 0.5,
    }

    # Injected ground-truth token
    corrupted_payload = dict(valid_payload, optimal_action="retry")
    resp1 = client.post("/api/v1/decisions", json=corrupted_payload)
    assert resp1.status_code == 422

    # Injected latent variable
    latent_payload = dict(valid_payload, latent_customer_intent=0.99)
    resp2 = client.post("/api/v1/decisions", json=latent_payload)
    assert resp2.status_code == 422

    # Random unknown extra field
    unknown_payload = dict(valid_payload, arbitrary_unregistered_key="foo")
    resp3 = client.post("/api/v1/decisions", json=unknown_payload)
    assert resp3.status_code == 422


def test_retry_exhaustion_safety_boundary(client):
    """When retry_count >= 2, RETRY must be disqualified."""
    payload = {
        "amount_paise": 300000,
        "currency": "INR",
        "payment_method": "card",
        "is_subscription": False,
        "customer_historical_success_rate": 0.75,
        "customer_total_transactions": 10,
        "customer_total_failures": 2,
        "customer_avg_amount_paise": 300000,
        "customer_tenure_months": 6,
        "failure_type": "insufficient_funds",
        "retry_count": 2,  # Retries exhausted
        "hours_since_failure": 12.0,
    }

    response = client.post("/api/v1/decisions", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["recommended_action"] != "retry"
    assert data["safety_status"]["retry_disqualified"] is True

    # Check candidate actions ledger
    retry_cand = next(c for c in data["candidate_actions"] if c["action"] == "retry")
    assert retry_cand["allowed"] is False
    assert "max_retries_exceeded" in retry_cand["disqualification_reason"]


def test_micro_ticket_escalation_safety_boundary(client):
    """When amount_paise < 20000 (< ₹200), ESCALATE must be disqualified."""
    payload = {
        "amount_paise": 15000,  # ₹150.00
        "currency": "INR",
        "payment_method": "upi",
        "is_subscription": False,
        "customer_historical_success_rate": 0.85,
        "customer_total_transactions": 8,
        "customer_total_failures": 1,
        "customer_avg_amount_paise": 15000,
        "customer_tenure_months": 4,
        "failure_type": "temporary_failure",
        "retry_count": 0,
        "hours_since_failure": 1.0,
    }

    response = client.post("/api/v1/decisions", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["recommended_action"] != "escalate"
    assert data["safety_status"]["escalate_disqualified"] is True

    escalate_cand = next(c for c in data["candidate_actions"] if c["action"] == "escalate")
    assert escalate_cand["allowed"] is False
    assert "micro_ticket_protection" in escalate_cand["disqualification_reason"]


def test_negative_intervention_ev_selects_no_action(client):
    """When all allowed interventions have negative expected net value, NO_ACTION must be chosen."""
    payload = {
        "amount_paise": 2000,  # ₹20.00 (< ₹200)
        "currency": "INR",
        "payment_method": "upi",
        "is_subscription": False,
        "customer_historical_success_rate": 0.40,
        "customer_total_transactions": 2,
        "customer_total_failures": 2,
        "customer_avg_amount_paise": 2000,
        "customer_tenure_months": 1,
        "failure_type": "invalid_payment_method",
        "retry_count": 2,  # Retries exhausted
        "hours_since_failure": 48.0,
    }

    response = client.post("/api/v1/decisions", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["recommended_action"] == "no_action"
    assert data["expected_net_recovery_paise"] == 0
    assert "NO ACTION" in data["explanation"].upper()


def test_decision_determinism(client):
    """Identical input requests must return identical economic evaluations and recommendations."""
    payload = {
        "amount_paise": 185000,
        "currency": "INR",
        "payment_method": "upi",
        "is_subscription": False,
        "customer_historical_success_rate": 0.92,
        "customer_total_transactions": 35,
        "customer_total_failures": 2,
        "customer_avg_amount_paise": 180000,
        "customer_tenure_months": 18,
        "failure_type": "temporary_failure",
        "retry_count": 0,
        "hours_since_failure": 0.5,
    }

    r1 = client.post("/api/v1/decisions", json=payload).json()
    r2 = client.post("/api/v1/decisions", json=payload).json()

    assert r1["recommended_action"] == r2["recommended_action"]
    assert r1["recommended_action_recovery_probability"] == r2["recommended_action_recovery_probability"]
    assert r1["expected_gross_recovery_paise"] == r2["expected_gross_recovery_paise"]
    assert r1["expected_net_recovery_paise"] == r2["expected_net_recovery_paise"]
    assert r1["decision_margin_paise"] == r2["decision_margin_paise"]


def test_degraded_service_when_model_unavailable():
    """Verify that when no model is loaded, health reports degraded and decisions returns 503."""
    from api.config import settings
    original_path = settings.model_path
    saved_engine = recovery_service._engine
    try:
        settings.model_path = Path("models/non_existent_model_file.pkl")
        recovery_service._engine = None  # Simulate model unavailable
        app = create_app()
        with TestClient(app) as test_client:
            health_resp = test_client.get("/api/v1/health")
            assert health_resp.status_code == 200
            assert health_resp.json()["status"] == "degraded"
            assert health_resp.json()["model_status"] == "model_unavailable"

            dec_resp = test_client.post("/api/v1/decisions", json={
                "amount_paise": 100000,
                "currency": "INR",
                "payment_method": "upi",
                "is_subscription": False,
                "customer_historical_success_rate": 0.9,
                "customer_total_transactions": 10,
                "customer_total_failures": 1,
                "customer_avg_amount_paise": 100000,
                "customer_tenure_months": 12,
                "failure_type": "temporary_failure",
                "retry_count": 0,
                "hours_since_failure": 1.0,
            })
            assert dec_resp.status_code == 503
            assert "unavailable" in dec_resp.json()["detail"].lower()
    finally:
        settings.model_path = original_path
        recovery_service._engine = saved_engine
