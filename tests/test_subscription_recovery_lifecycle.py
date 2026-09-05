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
    mock_invoices = [
        {"id": "inv_api_001", "amount": 350000, "amount_due": 350000, "amount_paid": 0, "status": "issued", "currency": "INR"}
    ]

    def _mock_request(method, endpoint, payload=None, params=None):
        if endpoint.startswith("/subscriptions/"):
            return mock_rzp_sub
        elif endpoint == "/invoices":
            return {"items": mock_invoices}
        return {}

    with patch("recovery.providers.razorpay.client.RazorpayClient._request", side_effect=_mock_request):
        resp_sync = client.post("/api/v1/recovery/subscriptions/sync", json={"subscription_id": "sub_api_test_001"})
        assert resp_sync.status_code == 200
        data_sync = resp_sync.json()
        assert data_sync["status"] == "active"
        assert data_sync["current_cycle"] == 2
        assert data_sync["amount_due_paise"] == 350000


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
    mock_invoices = [
        {"id": "inv_agent_001", "amount": 200000, "amount_due": 200000, "amount_paid": 0, "status": "issued", "currency": "INR"}
    ]

    def _mock_request(method, endpoint, payload=None, params=None):
        if endpoint.startswith("/subscriptions/"):
            return mock_rzp_sub
        elif endpoint == "/invoices":
            return {"items": mock_invoices}
        return {}

    with patch("recovery.providers.razorpay.client.RazorpayClient._request", side_effect=_mock_request):
        res = tool.execute(context, subscription_id="sub_agent_001")
        assert res["subscription_id"] == "sub_agent_001"
        assert res["status"] == "active"
        assert res["current_cycle"] == 1
        assert res["amount_due_paise"] == 200000


def test_sync_active_with_unpaid_invoice_not_recovered(client):
    """
    INVARIANT 1: Subscription ACTIVE does NOT mean case RECOVERED.
    When subscription is ACTIVE but specific invoice is unpaid (status=issued), case must remain ACTION_EXECUTED.
    """
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    settings.razorpay_key_id = "rzp_test_mock_123"
    settings.razorpay_key_secret = "mock_secret_123"
    repo = operations_service.repository

    # 1. Ingest failed charge -> Case created with ACTION_EXECUTED
    payload = make_subscription_pending_payload(
        subscription_id="sub_unpaid_test_001",
        customer_id="cust_unpaid_001",
        amount_paise=250000,
        invoice_id="inv_unpaid_001",
        event_id="evt_unpaid_001",
    )
    b = json.dumps(payload).encode("utf-8")
    client.post(
        "/api/v1/webhooks/razorpay",
        content=b,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_signature(b, settings.razorpay_webhook_secret), "X-Razorpay-Event-Id": "evt_unpaid_001"},
    )
    case_before = repo.get_case_by_billing_cycle("sub_unpaid_test_001", "inv_unpaid_001")
    assert case_before.current_state == CaseState.ACTION_EXECUTED

    # 2. Sync receives ACTIVE subscription, but invoice is STILL UNPAID
    mock_rzp_sub = {
        "id": "sub_unpaid_test_001",
        "entity": "subscription",
        "customer_id": "cust_unpaid_001",
        "status": "active",
        "current_count": 1,
        "auth_attempts": 1,
    }
    mock_invoices = [
        {"id": "inv_unpaid_001", "amount": 250000, "amount_due": 250000, "amount_paid": 0, "status": "issued", "currency": "INR"}
    ]

    def _mock_request(method, endpoint, payload=None, params=None):
        if endpoint.startswith("/subscriptions/"):
            return mock_rzp_sub
        elif endpoint == "/invoices":
            return {"items": mock_invoices}
        return {}

    with patch("recovery.providers.razorpay.client.RazorpayClient._request", side_effect=_mock_request):
        resp = client.post("/api/v1/recovery/subscriptions/sync", json={"subscription_id": "sub_unpaid_test_001"})
        assert resp.status_code == 200

    # 3. Assert case REMAINS in ACTION_EXECUTED (no false recovery)
    case_after = repo.get_case_by_billing_cycle("sub_unpaid_test_001", "inv_unpaid_001")
    assert case_after.current_state == CaseState.ACTION_EXECUTED
    assert case_after.outcome_status is None


def test_sync_active_with_paid_invoice_recovered(client):
    """
    INVARIANT 2: Genuine settlement evidence triggers RECOVERED state transition.
    When matching invoice is status=paid and amount_paid > 0, case transitions to RECOVERED.
    """
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    settings.razorpay_key_id = "rzp_test_mock_123"
    settings.razorpay_key_secret = "mock_secret_123"
    repo = operations_service.repository

    payload = make_subscription_pending_payload(
        subscription_id="sub_paid_test_001",
        customer_id="cust_paid_001",
        amount_paise=250000,
        invoice_id="inv_paid_001",
        event_id="evt_paid_001",
    )
    b = json.dumps(payload).encode("utf-8")
    client.post(
        "/api/v1/webhooks/razorpay",
        content=b,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_signature(b, settings.razorpay_webhook_secret), "X-Razorpay-Event-Id": "evt_paid_001"},
    )

    mock_rzp_sub = {
        "id": "sub_paid_test_001",
        "entity": "subscription",
        "customer_id": "cust_paid_001",
        "status": "active",
        "current_count": 1,
        "auth_attempts": 1,
    }
    mock_invoices = [
        {"id": "inv_paid_001", "amount": 250000, "amount_due": 0, "amount_paid": 250000, "status": "paid", "payment_id": "pay_autodebit_123", "currency": "INR"}
    ]

    def _mock_request(method, endpoint, payload=None, params=None):
        if endpoint.startswith("/subscriptions/"):
            return mock_rzp_sub
        elif endpoint == "/invoices":
            return {"items": mock_invoices}
        return {}

    with patch("recovery.providers.razorpay.client.RazorpayClient._request", side_effect=_mock_request):
        resp = client.post("/api/v1/recovery/subscriptions/sync", json={"subscription_id": "sub_paid_test_001"})
        assert resp.status_code == 200

    case_after = repo.get_case_by_billing_cycle("sub_paid_test_001", "inv_paid_001")
    assert case_after.current_state == CaseState.RECOVERED
    assert case_after.recovered_amount_paise == 250000
    assert case_after.resolution_source == RecoveryResolutionSource.PROVIDER_AUTO_RETRY.value


def test_sync_wrong_invoice_paid_not_recovered(client):
    """
    INVARIANT 3: Cycle 1 invoice paid does NOT settle Cycle 2 case.
    Explicit billing-cycle identity matching prevents cross-cycle false recoveries.
    """
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    settings.razorpay_key_id = "rzp_test_mock_123"
    settings.razorpay_key_secret = "mock_secret_123"
    repo = operations_service.repository

    # Ingest Cycle 2 failed charge
    payload = make_subscription_pending_payload(
        subscription_id="sub_cross_cycle_001",
        customer_id="cust_cross_001",
        amount_paise=180000,
        current_count=2,
        invoice_id="inv_cycle_2",
        event_id="evt_c2_001",
    )
    b = json.dumps(payload).encode("utf-8")
    client.post(
        "/api/v1/webhooks/razorpay",
        content=b,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_signature(b, settings.razorpay_webhook_secret), "X-Razorpay-Event-Id": "evt_c2_001"},
    )

    # Provider returns Cycle 1 as paid, but Cycle 2 as issued (unpaid)
    mock_rzp_sub = {
        "id": "sub_cross_cycle_001",
        "entity": "subscription",
        "customer_id": "cust_cross_001",
        "status": "active",
        "current_count": 2,
        "auth_attempts": 1,
    }
    mock_invoices = [
        {"id": "inv_cycle_1", "amount": 180000, "amount_due": 0, "amount_paid": 180000, "status": "paid", "currency": "INR"},
        {"id": "inv_cycle_2", "amount": 180000, "amount_due": 180000, "amount_paid": 0, "status": "issued", "currency": "INR"},
    ]

    def _mock_request(method, endpoint, payload=None, params=None):
        if endpoint.startswith("/subscriptions/"):
            return mock_rzp_sub
        elif endpoint == "/invoices":
            return {"items": mock_invoices}
        return {}

    with patch("recovery.providers.razorpay.client.RazorpayClient._request", side_effect=_mock_request):
        resp = client.post("/api/v1/recovery/subscriptions/sync", json={"subscription_id": "sub_cross_cycle_001"})
        assert resp.status_code == 200

    # Cycle 2 case must remain ACTION_EXECUTED (unsettled)
    case_c2 = repo.get_case_by_billing_cycle("sub_cross_cycle_001", "inv_cycle_2")
    assert case_c2.current_state == CaseState.ACTION_EXECUTED
    assert case_c2.outcome_status is None


def test_sync_cannot_fabricate_recovered_revenue(client):
    """
    INVARIANT 4: Sync cannot fabricate recovered revenue without provider invoice settlement evidence.
    """
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    settings.razorpay_key_id = "rzp_test_mock_123"
    settings.razorpay_key_secret = "mock_secret_123"
    repo = operations_service.repository

    payload = make_subscription_pending_payload(
        subscription_id="sub_nofab_001",
        customer_id="cust_nofab_001",
        amount_paise=400000,
        invoice_id="inv_nofab_001",
        event_id="evt_nofab_001",
    )
    b = json.dumps(payload).encode("utf-8")
    client.post(
        "/api/v1/webhooks/razorpay",
        content=b,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_signature(b, settings.razorpay_webhook_secret), "X-Razorpay-Event-Id": "evt_nofab_001"},
    )

    # Invoices list is empty / returns no paid evidence
    mock_rzp_sub = {
        "id": "sub_nofab_001",
        "entity": "subscription",
        "customer_id": "cust_nofab_001",
        "status": "completed",
        "current_count": 1,
        "auth_attempts": 0,
    }

    def _mock_request(method, endpoint, payload=None, params=None):
        if endpoint.startswith("/subscriptions/"):
            return mock_rzp_sub
        elif endpoint == "/invoices":
            return {"items": []}
        return {}

    with patch("recovery.providers.razorpay.client.RazorpayClient._request", side_effect=_mock_request):
        resp = client.post("/api/v1/recovery/subscriptions/sync", json={"subscription_id": "sub_nofab_001"})
        assert resp.status_code == 200

    case = repo.get_case_by_billing_cycle("sub_nofab_001", "inv_nofab_001")
    assert case.current_state == CaseState.ACTION_EXECUTED
    assert case.outcome_status is None


def test_sync_authoritative_invoice_amount_beats_notes(client):
    """
    INVARIANT 5: Authoritative provider invoice amount takes strict precedence over arbitrary notes metadata.
    """
    settings.razorpay_key_id = "rzp_test_mock_123"
    settings.razorpay_key_secret = "mock_secret_123"

    mock_rzp_sub = {
        "id": "sub_amount_auth_001",
        "entity": "subscription",
        "customer_id": "cust_auth_001",
        "status": "active",
        "current_count": 1,
        "notes": {"amount_paise": 100000, "currency": "USD"},  # Arbitrary/incorrect notes
    }
    mock_invoices = [
        {"id": "inv_auth_001", "amount": 500000, "amount_due": 500000, "amount_paid": 0, "status": "issued", "currency": "INR"}  # Authoritative
    ]

    def _mock_request(method, endpoint, payload=None, params=None):
        if endpoint.startswith("/subscriptions/"):
            return mock_rzp_sub
        elif endpoint == "/invoices":
            return {"items": mock_invoices}
        return {}

    with patch("recovery.providers.razorpay.client.RazorpayClient._request", side_effect=_mock_request):
        resp = client.post("/api/v1/recovery/subscriptions/sync", json={"subscription_id": "sub_amount_auth_001"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount_due_paise"] == 500000
        assert data["amount_due_inr"] == 5000.0
        assert data["currency"] == "INR"


def test_sync_paid_invoice_recovered_amount_uses_amount_paid(client):
    """
    INVARIANT 6: Recovered amount strictly uses invoice.amount_paid, not face value.
    """
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    settings.razorpay_key_id = "rzp_test_mock_123"
    settings.razorpay_key_secret = "mock_secret_123"
    repo = operations_service.repository

    payload = make_subscription_pending_payload(
        subscription_id="sub_partial_paid_001",
        customer_id="cust_partial_001",
        amount_paise=500000,
        invoice_id="inv_partial_001",
        event_id="evt_partial_001",
    )
    b = json.dumps(payload).encode("utf-8")
    client.post(
        "/api/v1/webhooks/razorpay",
        content=b,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_signature(b, settings.razorpay_webhook_secret), "X-Razorpay-Event-Id": "evt_partial_001"},
    )

    # Invoice face amount = 500000, but settled amount_paid = 450000
    mock_rzp_sub = {
        "id": "sub_partial_paid_001",
        "entity": "subscription",
        "customer_id": "cust_partial_001",
        "status": "active",
        "current_count": 1,
    }
    mock_invoices = [
        {"id": "inv_partial_001", "amount": 500000, "amount_due": 0, "amount_paid": 450000, "status": "paid", "payment_id": "pay_partial_123", "currency": "INR"}
    ]

    def _mock_request(method, endpoint, payload=None, params=None):
        if endpoint.startswith("/subscriptions/"):
            return mock_rzp_sub
        elif endpoint == "/invoices":
            return {"items": mock_invoices}
        return {}

    with patch("recovery.providers.razorpay.client.RazorpayClient._request", side_effect=_mock_request):
        resp = client.post("/api/v1/recovery/subscriptions/sync", json={"subscription_id": "sub_partial_paid_001"})
        assert resp.status_code == 200

    case = repo.get_case_by_billing_cycle("sub_partial_paid_001", "inv_partial_001")
    assert case.current_state == CaseState.RECOVERED
    assert case.recovered_amount_paise == 450000  # Exact integer amount_paid


def test_sync_ambiguous_settlement_source_not_attributed_to_recoverai(client):
    """
    INVARIANT 7: RecoverAI intervention attribution requires deterministic proof;
    ambiguous settlement source defaults to provider_auto_retry.
    """
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    settings.razorpay_key_id = "rzp_test_mock_123"
    settings.razorpay_key_secret = "mock_secret_123"
    repo = operations_service.repository

    payload = make_subscription_pending_payload(
        subscription_id="sub_ambig_001",
        customer_id="cust_ambig_001",
        amount_paise=200000,
        invoice_id="inv_ambig_001",
        event_id="evt_ambig_001",
    )
    b = json.dumps(payload).encode("utf-8")
    client.post(
        "/api/v1/webhooks/razorpay",
        content=b,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": compute_signature(b, settings.razorpay_webhook_secret), "X-Razorpay-Event-Id": "evt_ambig_001"},
    )

    # Payment settled through generic bank debit without RecoverAI payment link reference
    mock_rzp_sub = {
        "id": "sub_ambig_001",
        "entity": "subscription",
        "customer_id": "cust_ambig_001",
        "status": "active",
        "current_count": 1,
    }
    mock_invoices = [
        {"id": "inv_ambig_001", "amount": 200000, "amount_due": 0, "amount_paid": 200000, "status": "paid", "payment_id": "pay_generic_bank_999", "currency": "INR"}
    ]

    def _mock_request(method, endpoint, payload=None, params=None):
        if endpoint.startswith("/subscriptions/"):
            return mock_rzp_sub
        elif endpoint == "/invoices":
            return {"items": mock_invoices}
        return {}

    with patch("recovery.providers.razorpay.client.RazorpayClient._request", side_effect=_mock_request):
        resp = client.post("/api/v1/recovery/subscriptions/sync", json={"subscription_id": "sub_ambig_001"})
        assert resp.status_code == 200

    case = repo.get_case_by_billing_cycle("sub_ambig_001", "inv_ambig_001")
    assert case.current_state == CaseState.RECOVERED
    assert case.resolution_source == RecoveryResolutionSource.PROVIDER_AUTO_RETRY.value
    assert case.resolution_source != RecoveryResolutionSource.RECOVERAI_INTERVENTION.value


def test_sync_unknown_status_fails_closed(client):
    """
    INVARIANT 8: Unrecognized subscription status maps to UNKNOWN and fails closed.
    """
    settings.razorpay_key_id = "rzp_test_mock_123"
    settings.razorpay_key_secret = "mock_secret_123"
    repo = operations_service.repository

    mock_rzp_sub = {
        "id": "sub_unk_sync_001",
        "entity": "subscription",
        "customer_id": "cust_unk_001",
        "status": "paused_unrecognized_state",
        "current_count": 1,
    }

    def _mock_request(method, endpoint, payload=None, params=None):
        if endpoint.startswith("/subscriptions/"):
            return mock_rzp_sub
        elif endpoint == "/invoices":
            return {"items": []}
        return {}

    with patch("recovery.providers.razorpay.client.RazorpayClient._request", side_effect=_mock_request):
        resp = client.post("/api/v1/recovery/subscriptions/sync", json={"subscription_id": "sub_unk_sync_001"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"
        assert data["is_recoverable"] is False

    sub_rec = repo.get_subscription("sub_unk_sync_001")
    assert sub_rec.status == RazorpaySubscriptionStatus.UNKNOWN
    assert sub_rec.is_recoverable is False

