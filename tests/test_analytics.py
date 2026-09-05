"""
Comprehensive test suite for RecoverAI Merchant Recovery Analytics (Milestone 3 Phase C).
Tests overview analytics, action breakdown, failure types, retry counts, subscriptions,
trends, date filtering, zero-data behavior, financial reconciliation, and edge cases.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from simulator.config import RecoveryAction, FailureType, PaymentMethod
from recovery.repository import RecoveryRepository
from api.app import create_app
from api.services.recovery_service import recovery_service
from api.services.operations_service import operations_service
from analytics.service import analytics_service
from analytics.repository import AnalyticsRepository


@pytest.fixture(scope="module")
def client():
    # Use isolated shared in-memory DB for analytics during tests
    test_repo = RecoveryRepository(db_path=":memory:")
    operations_service.repository = test_repo
    analytics_service.repository = AnalyticsRepository(test_repo)

    # Load champion model
    model_path = Path("models/champion_recovery_model.pkl")
    recovery_service.load_model(model_path)

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_analytics_zero_data(client):
    """Verify that analytics endpoints handle empty database gracefully with 0.0 rates and zero counts."""
    # 1. Overview
    resp = client.get("/api/v1/analytics/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cases"] == 0
    assert data["decisions_made"] == 0
    assert data["actions_executed"] == 0
    assert data["recovered_cases"] == 0
    assert data["recovery_rate"] == 0.0
    assert data["execution_success_rate"] == 0.0
    assert data["gross_recovered_paise"] == 0
    assert data["net_recovered_paise"] == 0

    # 2. Actions (should return all 5 actions in deterministic order with 0 counts)
    resp_act = client.get("/api/v1/analytics/actions")
    assert resp_act.status_code == 200
    act_data = resp_act.json()
    assert len(act_data) == 5
    assert [item["action"] for item in act_data] == [
        "no_action",
        "retry",
        "payment_link",
        "reminder",
        "escalate",
    ]
    for item in act_data:
        assert item["decisions"] == 0
        assert item["recovery_rate"] == 0.0

    # 3. Failure Types (4 failure types with 0 counts)
    resp_ft = client.get("/api/v1/analytics/failure-types")
    assert resp_ft.status_code == 200
    ft_data = resp_ft.json()
    assert len(ft_data) == 4
    assert [item["failure_type"] for item in ft_data] == [
        "insufficient_funds",
        "invalid_payment_method",
        "temporary_failure",
        "unknown_failure",
    ]

    # 4. Subscriptions (2 segments with 0 counts)
    resp_sub = client.get("/api/v1/analytics/subscriptions")
    assert resp_sub.status_code == 200
    sub_data = resp_sub.json()
    assert len(sub_data) == 2
    assert [item["segment"] for item in sub_data] == ["one_off", "subscription"]

    # 5. Trends (empty list when no data)
    resp_tr = client.get("/api/v1/analytics/trends")
    assert resp_tr.status_code == 200
    assert resp_tr.json() == []


def test_populated_analytics_flow_and_reconciliation(client):
    """
    Test populated analytics lifecycle:
    Case 1: ₹3,000 temp failure, upi, one_off -> Decision -> Action Executed (retry) -> Recovered (₹3,000)
    Case 2: ₹1,500 insufficient funds, card, subscription -> Decision -> Action Executed (payment_link) -> Not Recovered (₹0)
    Case 3: ₹5,000 temp failure, mandate, subscription -> Decision -> Action Executed (retry) -> Failed Execution (provider error)
    Case 4: ₹2,000 invalid method, upi, one_off -> Decision (Pending action)
    """
    # Case 1: Recovered (₹3,000.00 / 300,000 paise)
    r1 = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_an_001",
            "customer_id": "cust_an_001",
            "amount_paise": 300000,
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.95,
            "customer_total_transactions": 25,
            "customer_total_failures": 1,
            "customer_avg_amount_paise": 300000,
            "customer_tenure_months": 18,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.2,
        },
    )
    d1 = r1.json()
    a1 = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": d1["decision_id"],
            "action": d1["recommended_action"],
            "idempotency_key": "idemp_an_001",
        },
    ).json()
    client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_an_001",
            "action_id": a1["action_id"],
            "decision_id": d1["decision_id"],
            "outcome_status": "recovered",
            "recovered_amount_paise": 300000,
        },
    )

    # Case 2: Not Recovered (₹1,500.00 / 150,000 paise)
    r2 = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_an_002",
            "customer_id": "cust_an_002",
            "amount_paise": 150000,
            "currency": "INR",
            "payment_method": "card",
            "is_subscription": True,
            "customer_historical_success_rate": 0.80,
            "customer_total_transactions": 10,
            "customer_total_failures": 2,
            "customer_avg_amount_paise": 150000,
            "customer_tenure_months": 6,
            "failure_type": "insufficient_funds",
            "retry_count": 1,
            "hours_since_failure": 1.5,
        },
    )
    d2 = r2.json()
    a2 = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": d2["decision_id"],
            "action": d2["recommended_action"],
            "idempotency_key": "idemp_an_002",
        },
    ).json()
    client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_an_002",
            "action_id": a2["action_id"],
            "decision_id": d2["decision_id"],
            "outcome_status": "not_recovered",
            "recovered_amount_paise": 0,
        },
    )

    # Case 3: Action Technical Failure
    r3 = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_an_003",
            "customer_id": "cust_an_003",
            "amount_paise": 500000,
            "currency": "INR",
            "payment_method": "mandate",
            "is_subscription": True,
            "customer_historical_success_rate": 0.88,
            "customer_total_transactions": 12,
            "customer_total_failures": 1,
            "customer_avg_amount_paise": 500000,
            "customer_tenure_months": 8,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.5,
        },
    )
    d3 = r3.json()
    client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": d3["decision_id"],
            "action": d3["recommended_action"],
            "idempotency_key": "idemp_an_003",
            "force_failure": True,
        },
    )

    # Case 4: Pending Case (Decision made, no action executed)
    client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_an_004",
            "customer_id": "cust_an_004",
            "amount_paise": 200000,
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.70,
            "customer_total_transactions": 5,
            "customer_total_failures": 2,
            "customer_avg_amount_paise": 200000,
            "customer_tenure_months": 3,
            "failure_type": "invalid_payment_method",
            "retry_count": 0,
            "hours_since_failure": 0.5,
        },
    )

    # Verify Overview Analytics
    resp_ov = client.get("/api/v1/analytics/overview")
    assert resp_ov.status_code == 200
    ov = resp_ov.json()

    assert ov["total_cases"] == 4
    assert ov["decisions_made"] == 4
    assert ov["actions_attempted"] == 3
    assert ov["actions_executed"] == 2
    assert ov["execution_failures"] == 1
    assert ov["recovered_cases"] == 1
    assert ov["not_recovered_cases"] == 1
    assert ov["pending_cases"] == 2  # Case 4 (DECIDED) + Case 3 (EXECUTION_FAILED / pending resolution)

    # Recovery rate: 1 / (1 + 1) = 0.50 (50%)
    assert pytest.approx(ov["recovery_rate"]) == 0.50

    # Success rate: 2 / 3 = 0.6667
    assert pytest.approx(ov["execution_success_rate"]) == 2.0 / 3.0
    assert pytest.approx(ov["execution_failure_rate"]) == 1.0 / 3.0

    # Financial Reconciliation
    assert ov["gross_recovered_paise"] == 300000
    assert ov["gross_recovered_inr"] == 3000.0
    # Cost = a1 cost + a2 cost (failed execution a3 has 0 cost)
    expected_cost = a1["cost_paise"] + a2["cost_paise"]
    assert ov["total_action_cost_paise"] == expected_cost
    assert ov["net_recovered_paise"] == 300000 - expected_cost
    assert ov["net_recovered_inr"] == (300000 - expected_cost) / 100.0


def test_action_analytics_breakdown(client):
    """Verify action-level breakdown statistics."""
    resp = client.get("/api/v1/analytics/actions")
    assert resp.status_code == 200
    actions_list = resp.json()
    assert len(actions_list) == 5

    # Check that sum of decisions across actions equals total decisions
    total_decisions = sum(a["decisions"] for a in actions_list)
    assert total_decisions >= 4


def test_failure_type_analytics_breakdown(client):
    """Verify failure type breakdown statistics."""
    resp = client.get("/api/v1/analytics/failure-types")
    assert resp.status_code == 200
    ft_list = resp.json()
    assert len(ft_list) == 4

    ft_map = {item["failure_type"]: item for item in ft_list}
    assert ft_map["temporary_failure"]["cases"] >= 2
    assert ft_map["insufficient_funds"]["cases"] >= 1
    assert ft_map["invalid_payment_method"]["cases"] >= 1


def test_retry_count_analytics_breakdown(client):
    """Verify retry count breakdown statistics."""
    resp = client.get("/api/v1/analytics/retry-count")
    assert resp.status_code == 200
    rc_list = resp.json()
    assert len(rc_list) >= 2  # retry_count 0 and retry_count 1 exist


def test_subscription_analytics_breakdown(client):
    """Verify subscription breakdown statistics."""
    resp = client.get("/api/v1/analytics/subscriptions")
    assert resp.status_code == 200
    sub_list = resp.json()
    assert len(sub_list) == 2
    sub_map = {item["segment"]: item for item in sub_list}
    assert sub_map["one_off"]["cases"] >= 2
    assert sub_map["subscription"]["cases"] >= 2


def test_trends_analytics_and_interval(client):
    """Verify time-series trends in daily and weekly intervals."""
    # Daily
    resp_d = client.get("/api/v1/analytics/trends?interval=daily")
    assert resp_d.status_code == 200
    trends_d = resp_d.json()
    assert len(trends_d) >= 1
    assert "time_bucket" in trends_d[0]

    # Weekly
    resp_w = client.get("/api/v1/analytics/trends?interval=weekly")
    assert resp_w.status_code == 200
    trends_w = resp_w.json()
    assert len(trends_w) >= 1

    # Invalid interval -> 422
    resp_inv = client.get("/api/v1/analytics/trends?interval=hourly")
    assert resp_inv.status_code == 422


def test_date_filtering_and_validation(client):
    """Verify date filtering and rejection of invalid date ranges."""
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    start_str = (now_utc - timedelta(days=7)).strftime("%Y-%m-%d")
    end_str = (now_utc + timedelta(days=7)).strftime("%Y-%m-%d")

    # Valid date filter
    resp = client.get(f"/api/v1/analytics/overview?start_date={start_str}&end_date={end_str}")
    assert resp.status_code == 200
    assert resp.json()["total_cases"] >= 4

    # Future date filter (empty window)
    resp_future = client.get("/api/v1/analytics/overview?start_date=2030-01-01&end_date=2030-12-31")
    assert resp_future.status_code == 200
    assert resp_future.json()["total_cases"] == 0

    # Invalid date range (start_date > end_date) -> 422
    resp_bad = client.get(f"/api/v1/analytics/overview?start_date={end_str}&end_date={start_str}")
    assert resp_bad.status_code == 422
    assert "cannot be after" in resp_bad.json()["detail"]


def test_recovery_summary_compatibility(client):
    """Ensure existing GET /api/v1/recovery/summary endpoint remains fully operational and backward-compatible."""
    resp = client.get("/api/v1/recovery/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_cases" in data
    assert "gross_recovered_paise" in data
    assert "total_action_cost_paise" in data
    assert "net_recovered_paise" in data
    assert data["net_recovered_paise"] == data["gross_recovered_paise"] - data["total_action_cost_paise"]
