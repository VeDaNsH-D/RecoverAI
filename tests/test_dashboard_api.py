"""
Unit and Integration Tests for Merchant Recovery Command Center Overview & Static Routes (Milestone 9).
Tests:
1. /api/v1/dashboard/overview empty and populated states.
2. Authoritative attribution isolation (RecoverAI Net vs Provider Auto-Retry Gross).
3. 5-Stage conversion funnel verification.
4. Static dashboard HTML serving at GET /dashboard.
5. Root redirect from GET / to /dashboard.
6. Date filtering and validation.
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
        yield test_client


def test_dashboard_overview_empty_state(client):
    """Verifies that an empty database returns clean zero counters and null/empty sub-objects."""
    resp = client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_cases"] == 0
    assert data["decisions_made"] == 0
    assert data["actions_executed"] == 0
    assert data["recovered_cases"] == 0
    assert data["gross_recovered_paise"] == 0
    assert data["recoverai_gross_recovered_paise"] == 0
    assert data["provider_gross_recovered_paise"] == 0
    assert data["recoverai_net_recovered_paise"] == 0
    assert data["total_action_cost_paise"] == 0
    assert data["recovery_rate"] == 0.0

    assert data["funnel"]["cases_at_risk"] == 0
    assert data["funnel"]["recovered_outcomes"] == 0
    assert data["attribution"]["recoverai_intervention_recovered_cases"] == 0
    assert data["attribution"]["provider_auto_retry_recovered_cases"] == 0
    assert data["attribution"]["unresolved_cases"] == 0


def test_dashboard_overview_populated_with_attribution_isolation(client):
    """
    Sets up 4 distinct cases:
    - Case 1: ₹5,000 failure -> Action Executed (payment_link) -> Settled RECOVERED via RecoverAI (resolution_source=recoverai_intervention)
    - Case 2: ₹3,000 failure -> Action Executed (retry) -> Settled RECOVERED via Provider (resolution_source=provider_auto_retry)
    - Case 3: ₹2,000 failure -> Action Executed (reminder) -> Settled NOT_RECOVERED
    - Case 4: ₹1,000 failure -> Decision Made (pending action dispatch)

    Verifies:
    - Gross Recovered = ₹8,000 (800,000 paise)
    - RecoverAI Gross = ₹5,000 (500,000 paise)
    - Provider Gross = ₹3,000 (300,000 paise)
    - RecoverAI Net = RecoverAI Gross - Action Costs (Provider Gross NEVER included in Net Recovered)
    - Conversion Funnel stages
    - Attribution counts
    """
    # 1. Case 1 (RecoverAI intervention recovered)
    r1 = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_dash_001",
            "customer_id": "cust_dash_001",
            "amount_paise": 500000,
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.90,
            "customer_total_transactions": 20,
            "customer_total_failures": 1,
            "customer_avg_amount_paise": 500000,
            "customer_tenure_months": 12,
            "failure_type": "insufficient_funds",
            "retry_count": 0,
            "hours_since_failure": 0.5,
        },
    )
    d1 = r1.json()
    a1 = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": d1["decision_id"],
            "action": d1["recommended_action"],
            "idempotency_key": "idemp_dash_001",
        },
    ).json()
    client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_dash_001",
            "action_id": a1["action_id"],
            "decision_id": d1["decision_id"],
            "outcome_status": "recovered",
            "recovered_amount_paise": 500000,
            "resolution_source": "recoverai_intervention",
        },
    )

    # 2. Case 2 (Provider auto-retry recovered)
    r2 = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_dash_002",
            "customer_id": "cust_dash_002",
            "amount_paise": 300000,
            "currency": "INR",
            "payment_method": "card",
            "is_subscription": True,
            "customer_historical_success_rate": 0.85,
            "customer_total_transactions": 15,
            "customer_total_failures": 2,
            "customer_avg_amount_paise": 300000,
            "customer_tenure_months": 10,
            "failure_type": "temporary_failure",
            "retry_count": 1,
            "hours_since_failure": 0.8,
        },
    )
    d2 = r2.json()
    a2 = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": d2["decision_id"],
            "action": d2["recommended_action"],
            "idempotency_key": "idemp_dash_002",
        },
    ).json()
    client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_dash_002",
            "action_id": a2["action_id"],
            "decision_id": d2["decision_id"],
            "outcome_status": "recovered",
            "recovered_amount_paise": 300000,
            "resolution_source": "provider_auto_retry",
        },
    )

    # 3. Case 3 (Not recovered)
    r3 = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_dash_003",
            "customer_id": "cust_dash_003",
            "amount_paise": 200000,
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.60,
            "customer_total_transactions": 8,
            "customer_total_failures": 3,
            "customer_avg_amount_paise": 200000,
            "customer_tenure_months": 4,
            "failure_type": "invalid_payment_method",
            "retry_count": 0,
            "hours_since_failure": 2.0,
        },
    )
    d3 = r3.json()
    a3 = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": d3["decision_id"],
            "action": d3["recommended_action"],
            "idempotency_key": "idemp_dash_003",
        },
    ).json()
    client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_dash_003",
            "action_id": a3["action_id"],
            "decision_id": d3["decision_id"],
            "outcome_status": "not_recovered",
            "recovered_amount_paise": 0,
        },
    )

    # 4. Case 4 (Pending decision, no action yet)
    client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_dash_004",
            "customer_id": "cust_dash_004",
            "amount_paise": 100000,
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.75,
            "customer_total_transactions": 5,
            "customer_total_failures": 1,
            "customer_avg_amount_paise": 100000,
            "customer_tenure_months": 2,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.1,
        },
    )

    # Query Overview Endpoint
    resp = client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 200
    ov = resp.json()

    # Total counts
    assert ov["total_cases"] == 4
    assert ov["decisions_made"] == 4
    assert ov["actions_attempted"] == 3
    assert ov["actions_executed"] == 3
    assert ov["recovered_cases"] == 2
    assert ov["not_recovered_cases"] == 1
    assert ov["pending_cases"] == 1

    # Financial sums & strict integer paise
    assert ov["total_amount_at_risk_paise"] == 1100000  # 5k + 3k + 2k + 1k
    assert ov["gross_recovered_paise"] == 800000        # 5k + 3k
    assert ov["recoverai_gross_recovered_paise"] == 500000
    assert ov["provider_gross_recovered_paise"] == 300000

    total_cost = a1["cost_paise"] + a2["cost_paise"] + a3["cost_paise"]
    assert ov["total_action_cost_paise"] == total_cost

    # INVARIANT: RecoverAI Net = RecoverAI Gross - Action Costs
    # Provider auto-retry is isolated and NEVER added into RecoverAI Net Recovered
    expected_net = 500000 - total_cost
    assert ov["recoverai_net_recovered_paise"] == expected_net

    # Funnel
    funnel = ov["funnel"]
    assert funnel["cases_at_risk"] == 4
    assert funnel["decisions_evaluated"] == 4
    assert funnel["interventions_dispatched"] == 3
    assert funnel["successful_executions"] == 3
    assert funnel["recovered_outcomes"] == 2

    # Attribution
    attribution = ov["attribution"]
    assert attribution["recoverai_intervention_recovered_cases"] == 1
    assert attribution["provider_auto_retry_recovered_cases"] == 1
    assert attribution["unresolved_cases"] == 2  # 1 not_recovered + 1 pending


def test_static_dashboard_route_and_root_redirect(client):
    """
    Verifies that:
    1. GET /dashboard returns 200 with HTML content.
    2. GET / redirects to /dashboard with status 307.
    """
    # 1. Static SPA
    resp_dash = client.get("/dashboard", follow_redirects=False)
    # Fastapi StaticFiles with html=True may return 200 on /dashboard or /dashboard/
    if resp_dash.status_code == 307:
        resp_dash = client.get(resp_dash.headers["location"])
    assert resp_dash.status_code == 200
    assert "RecoverAI" in resp_dash.text
    assert "Command Center" in resp_dash.text

    # 2. Root Redirect
    resp_root = client.get("/", follow_redirects=False)
    assert resp_root.status_code == 307
    assert resp_root.headers["location"] == "/dashboard"

    # 3. Landing Page
    resp_landing = client.get("/landing")
    assert resp_landing.status_code == 200
    assert "RecoverAI" in resp_landing.text
    assert "Transform failed payments" in resp_landing.text


def test_dashboard_overview_date_validation(client):
    """Verifies rejection of invalid date ranges with 422."""
    resp = client.get("/api/v1/dashboard/overview?start_date=2026-09-30&end_date=2026-09-01")
    assert resp.status_code == 422
    assert "cannot be after" in resp.json()["detail"]
