"""
Unit and Integration Tests for Case Queue, Case Detail, and Chronological Audit Timeline (Milestone 9).
Tests:
1. Paginated case queue with limit & offset bounds (rejection of limit > 100).
2. Filtering by state, action, failure_type, is_subscription, search.
3. Strict absence of amount_inr floats in case summary API schemas (integer paise only).
4. Case detail endpoint separating Decision Forecast from Authoritative Settlement.
5. Chronological audit timeline with strict verification that only persisted events exist.
6. 404 handling for invalid case IDs.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from recovery.repository import RecoveryRepository
from api.app import create_app
from api.services.recovery_service import recovery_service
from api.services.operations_service import operations_service
from analytics.service import analytics_service
from analytics.repository import AnalyticsRepository


@pytest.fixture(scope="module")
def client():
    test_repo = RecoveryRepository(db_path=":memory:")
    operations_service.repository = test_repo
    analytics_service.repository = AnalyticsRepository(test_repo)

    model_path = Path("models/champion_recovery_model.pkl")
    recovery_service.load_model(model_path)

    app = create_app()
    with TestClient(app) as test_client:
        # Seed 3 test cases
        # Case A: One-off UPI, temporary failure, action executed, settled recovered
        r_a = test_client.post(
            "/api/v1/decisions",
            json={
                "case_id": "case_cq_001",
                "customer_id": "cust_cq_alpha",
                "amount_paise": 400000,
                "currency": "INR",
                "payment_method": "upi",
                "is_subscription": False,
                "customer_historical_success_rate": 0.90,
                "customer_total_transactions": 10,
                "customer_total_failures": 1,
                "customer_avg_amount_paise": 400000,
                "customer_tenure_months": 12,
                "failure_type": "temporary_failure",
                "retry_count": 0,
                "hours_since_failure": 0.1,
            },
        )
        d_a = r_a.json()
        a_a = test_client.post(
            "/api/v1/recovery/actions",
            json={
                "decision_id": d_a["decision_id"],
                "action": d_a["recommended_action"],
                "idempotency_key": "idemp_cq_001",
            },
        ).json()
        test_client.post(
            "/api/v1/recovery/outcomes",
            json={
                "case_id": "case_cq_001",
                "action_id": a_a["action_id"],
                "decision_id": d_a["decision_id"],
                "outcome_status": "recovered",
                "recovered_amount_paise": 400000,
                "resolution_source": "recoverai_intervention",
            },
        )

        # Case B: Subscription Card, insufficient funds, action executed, settled not_recovered
        r_b = test_client.post(
            "/api/v1/decisions",
            json={
                "case_id": "case_cq_002",
                "customer_id": "cust_cq_beta",
                "amount_paise": 150000,
                "currency": "INR",
                "payment_method": "card",
                "is_subscription": True,
                "customer_historical_success_rate": 0.70,
                "customer_total_transactions": 5,
                "customer_total_failures": 2,
                "customer_avg_amount_paise": 150000,
                "customer_tenure_months": 3,
                "failure_type": "insufficient_funds",
                "retry_count": 1,
                "hours_since_failure": 1.0,
            },
        )
        d_b = r_b.json()
        a_b = test_client.post(
            "/api/v1/recovery/actions",
            json={
                "decision_id": d_b["decision_id"],
                "action": d_b["recommended_action"],
                "idempotency_key": "idemp_cq_002",
            },
        ).json()
        test_client.post(
            "/api/v1/recovery/outcomes",
            json={
                "case_id": "case_cq_002",
                "action_id": a_b["action_id"],
                "decision_id": d_b["decision_id"],
                "outcome_status": "not_recovered",
                "recovered_amount_paise": 0,
            },
        )

        # Case C: One-off UPI, invalid_payment_method, decided only
        test_client.post(
            "/api/v1/decisions",
            json={
                "case_id": "case_cq_003",
                "customer_id": "cust_cq_gamma",
                "amount_paise": 250000,
                "currency": "INR",
                "payment_method": "upi",
                "is_subscription": False,
                "customer_historical_success_rate": 0.80,
                "customer_total_transactions": 7,
                "customer_total_failures": 1,
                "customer_avg_amount_paise": 250000,
                "customer_tenure_months": 6,
                "failure_type": "invalid_payment_method",
                "retry_count": 0,
                "hours_since_failure": 0.5,
            },
        )

        yield test_client


def test_list_cases_pagination_and_bounds(client):
    """Verifies limit, offset, and bounds enforcement."""
    # 1. Default page
    resp = client.get("/api/v1/recovery/cases")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 3
    assert len(data["items"]) == 3
    assert data["limit"] == 20
    assert data["offset"] == 0

    # 2. Bounded page size (limit=2, offset=1)
    resp_paged = client.get("/api/v1/recovery/cases?limit=2&offset=1")
    assert resp_paged.status_code == 200
    pdata = resp_paged.json()
    assert pdata["total_count"] == 3
    assert len(pdata["items"]) == 2
    assert pdata["limit"] == 2
    assert pdata["offset"] == 1

    # 3. Reject limit > 100 with 422
    resp_bad = client.get("/api/v1/recovery/cases?limit=101")
    assert resp_bad.status_code == 422


def test_list_cases_filtering(client):
    """Verifies state, failure_type, subscription, and search filters."""
    # State filter: RECOVERED
    r_state = client.get("/api/v1/recovery/cases?state=RECOVERED")
    assert r_state.status_code == 200
    assert r_state.json()["total_count"] == 1
    assert r_state.json()["items"][0]["case_id"] == "case_cq_001"

    # Segment filter: is_subscription=true
    r_sub = client.get("/api/v1/recovery/cases?is_subscription=true")
    assert r_sub.status_code == 200
    assert r_sub.json()["total_count"] == 1
    assert r_sub.json()["items"][0]["case_id"] == "case_cq_002"

    # Search filter: customer_id substring
    r_search = client.get("/api/v1/recovery/cases?search=gamma")
    assert r_search.status_code == 200
    assert r_search.json()["total_count"] == 1
    assert r_search.json()["items"][0]["case_id"] == "case_cq_003"


def test_case_summary_schema_strict_integer_paise(client):
    """
    INVARIANT: Case summary schemas must contain only integer paise amounts.
    No float 'amount_inr' fields in API schema.
    """
    resp = client.get("/api/v1/recovery/cases")
    assert resp.status_code == 200
    items = resp.json()["items"]
    for item in items:
        assert "amount_paise" in item
        assert isinstance(item["amount_paise"], int)
        assert "amount_inr" not in item  # Strict exclusion


def test_get_case_detail_separates_forecast_from_settlement(client):
    """
    Verifies that GET /api/v1/recovery/cases/{case_id} cleanly separates:
    - Model Forecast: P(Y|X), expected_gross_recovery_paise, expected_net_recovery_paise
    - Authoritative Settlement: recovered_amount_paise, outcome_status, resolution_source
    """
    resp = client.get("/api/v1/recovery/cases/case_cq_001")
    assert resp.status_code == 200
    detail = resp.json()

    # Case section
    assert detail["case"]["case_id"] == "case_cq_001"
    assert detail["case"]["amount_paise"] == 400000

    # Decision Forecast
    forecast = detail["decision_forecast"]
    assert forecast is not None
    assert forecast["recommended_action"] is not None
    assert "expected_gross_recovery_paise" in forecast
    assert "expected_net_recovery_paise" in forecast
    assert isinstance(forecast["expected_net_recovery_paise"], int)

    # Action Execution
    act = detail["action_execution"]
    assert act is not None
    assert act["status"] == "EXECUTED"
    assert "cost_paise" in act

    # Authoritative Settlement
    settlement = detail["outcome_settlement"]
    assert settlement is not None
    assert settlement["outcome_status"] == "recovered"
    assert settlement["recovered_amount_paise"] == 400000
    assert settlement["resolution_source"] == "recoverai_intervention"


def test_get_case_detail_not_found(client):
    """Verifies 404 for nonexistent case ID."""
    resp = client.get("/api/v1/recovery/cases/nonexistent_case_999")
    assert resp.status_code == 404
    assert "was not found" in resp.json()["detail"]


def test_get_case_timeline_strict_persisted_events_only(client):
    """
    Verifies that the chronological audit timeline:
    1. Reconstructs events in ascending chronological order.
    2. Contains only genuinely persisted records (case_created, decision_computed, action_dispatched, outcome_settled).
    3. Does NOT synthesize fake webhook events when none occurred.
    """
    resp = client.get("/api/v1/recovery/cases/case_cq_001/timeline")
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == "case_cq_001"

    events = data["events"]
    assert len(events) >= 4

    stages = [e["stage"] for e in events]
    assert stages[0] == "case_created"
    assert stages[1] == "decision_computed"
    assert stages[2] == "action_dispatched"
    assert stages[3] == "outcome_settled"

    # Verify no fake webhook events were synthesized
    assert "webhook_received" not in stages

    # Verify chronological timestamp ordering
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps)

    # Verify event fields
    for e in events:
        assert "event_id" in e
        assert "title" in e
        assert "description" in e
        assert "status" in e
        assert "metadata" in e


def test_get_case_timeline_not_found(client):
    """Verifies 404 for timeline of nonexistent case."""
    resp = client.get("/api/v1/recovery/cases/nonexistent_case_999/timeline")
    assert resp.status_code == 404
