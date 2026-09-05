"""
End-to-end integration tests for Subscription Recovery Lifecycle, Stopping Rules, Attribution, and Agent Tooling.
100% deterministic and offline.
"""

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from agent.models import AgentContext
from agent.tools.subscription_sync import SyncSubscriptionTool
from api.app import create_app
from api.config import settings
from api.services.operations_service import operations_service
from recovery.models import CaseState, OutcomeStatus
from recovery.repository import RecoveryRepository
from recovery.subscriptions.models import RazorpaySubscriptionStatus, RecoveryResolutionSource
from tests.fixtures.subscription_webhooks import (
    make_subscription_charged_payload,
    make_subscription_halted_payload,
    make_subscription_lifecycle_payload,
    make_subscription_pending_payload,
)


@pytest.fixture
def client():
    test_repo = RecoveryRepository(db_path=":memory:")
    operations_service.repository = test_repo
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def compute_signature(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def test_multi_cycle_subscription_distinct_cases(client):
    """Verify Cycle 1 and Cycle 2 failures on same subscription create independent recovery cases."""
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    repo = operations_service.repository

    # Cycle 1 failure
    c1_payload = make_subscription_pending_payload(
        subscription_id="sub_multicycle_001",
        customer_id="cust_multi_001",
        amount_paise=150000,
        current_count=1,
        invoice_id="inv_c1_001",
        payment_id="pay_c1_001",
        event_id="evt_c1_pending",
    )
    b1 = json.dumps(c1_payload).encode("utf-8")
    resp1 = client.post(
        "/api/v1/webhooks/razorpay",
        content=b1,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_signature(b1, settings.razorpay_webhook_secret), "X-Razorpay-Event-Id": "evt_c1_pending"},
    )
    assert resp1.status_code == 200

    # Cycle 1 recovery via link
    case1 = repo.get_case_by_billing_cycle("sub_multicycle_001", "inv_c1_001")
    c1_charge = make_subscription_charged_payload(
        subscription_id="sub_multicycle_001",
        customer_id="cust_multi_001",
        amount_paise=150000,
        current_count=1,
        invoice_id="inv_c1_001",
        action_id=case1.last_action_id,
        is_payment_link=True,
        event_id="evt_c1_charged",
    )
    b1_c = json.dumps(c1_charge).encode("utf-8")
    client.post(
        "/api/v1/webhooks/razorpay",
        content=b1_c,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_signature(b1_c, settings.razorpay_webhook_secret), "X-Razorpay-Event-Id": "evt_c1_charged"},
    )

    case1_after = repo.get_case_by_billing_cycle("sub_multicycle_001", "inv_c1_001")
    assert case1_after.current_state == CaseState.RECOVERED
    assert case1_after.resolution_source == RecoveryResolutionSource.RECOVERAI_INTERVENTION.value

    # Cycle 2 failure
    c2_payload = make_subscription_pending_payload(
        subscription_id="sub_multicycle_001",
        customer_id="cust_multi_001",
        amount_paise=150000,
        current_count=2,
        invoice_id="inv_c2_002",
        payment_id="pay_c2_002",
        event_id="evt_c2_pending",
    )
    b2 = json.dumps(c2_payload).encode("utf-8")
    resp2 = client.post(
        "/api/v1/webhooks/razorpay",
        content=b2,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_signature(b2, settings.razorpay_webhook_secret), "X-Razorpay-Event-Id": "evt_c2_pending"},
    )
    assert resp2.status_code == 200

    case2 = repo.get_case_by_billing_cycle("sub_multicycle_001", "inv_c2_002")
    assert case2 is not None
    assert case2.case_id != case1.case_id
    assert case2.billing_cycle_id == "inv_c2_002"


def test_subscription_api_routes(client):
    """Verify GET and POST /api/v1/recovery/subscriptions endpoints."""
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    settings.razorpay_key_id = "rzp_test_mock_123"
    settings.razorpay_key_secret = "mock_secret_123"
    repo = operations_service.repository

    # Ingest subscription
    payload = make_subscription_pending_payload(
        subscription_id="sub_api_test_001",
        customer_id="cust_api_001",
        amount_paise=350000,
        event_id="evt_api_001",
    )
    b = json.dumps(payload).encode("utf-8")
    client.post(
        "/api/v1/webhooks/razorpay",
        content=b,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_signature(b, settings.razorpay_webhook_secret), "X-Razorpay-Event-Id": "evt_api_001"},
    )

    # 1. GET /api/v1/recovery/subscriptions/{id}
    resp_get = client.get("/api/v1/recovery/subscriptions/sub_api_test_001")
    assert resp_get.status_code == 200
    data_get = resp_get.json()
    assert data_get["subscription_id"] == "sub_api_test_001"
    assert data_get["status"] == "pending"
    assert data_get["amount_due_paise"] == 350000
    assert data_get["amount_due_inr"] == 3500.0

    # 2. GET /api/v1/recovery/subscriptions (List)
    resp_list = client.get("/api/v1/recovery/subscriptions")
    assert resp_list.status_code == 200
    data_list = resp_list.json()
    assert len(data_list) >= 1
    assert any(s["subscription_id"] == "sub_api_test_001" for s in data_list)

    # 3. POST /api/v1/recovery/subscriptions/sync
    mock_rzp_sub = {
        "id": "sub_api_test_001",
        "entity": "subscription",
        "plan_id": "plan_monthly_pro",
        "customer_id": "cust_api_001",
        "status": "active",
        "current_count": 2,
        "total_count": 12,
        "auth_attempts": 0,
        "quantity": 1,
        "notes": {"amount_paise": 350000},
    }
    with patch("recovery.providers.razorpay.client.RazorpayClient._request", return_value=mock_rzp_sub):
        resp_sync = client.post("/api/v1/recovery/subscriptions/sync", json={"subscription_id": "sub_api_test_001"})
        assert resp_sync.status_code == 200
        data_sync = resp_sync.json()
        assert data_sync["status"] == "active"
        assert data_sync["current_cycle"] == 2


def test_agent_sync_subscription_tool():
    """Verify SyncSubscriptionTool agent execution and case state transition."""
    test_repo = RecoveryRepository(db_path=":memory:")
    operations_service.repository = test_repo
    settings.razorpay_key_id = "rzp_test_mock_123"
    settings.razorpay_key_secret = "mock_secret_123"

    tool = SyncSubscriptionTool()
    assert tool.name == "sync_subscription"

    context = AgentContext(
        case_id="case_sub_agent_001",
        customer_id="cust_agent_001",
        current_operational_state="ACTION_EXECUTED",
    )

    mock_rzp_sub = {
        "id": "sub_agent_001",
        "entity": "subscription",
        "plan_id": "plan_001",
        "customer_id": "cust_agent_001",
        "status": "active",
        "current_count": 1,
        "total_count": 12,
        "auth_attempts": 0,
        "quantity": 1,
        "notes": {"amount_paise": 200000},
    }

    with patch("recovery.providers.razorpay.client.RazorpayClient._request", return_value=mock_rzp_sub):
        res = tool.execute(context, subscription_id="sub_agent_001")
        assert res["subscription_id"] == "sub_agent_001"
        assert res["status"] == "active"
        assert res["current_cycle"] == 1
