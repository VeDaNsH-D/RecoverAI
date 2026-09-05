"""
Integration tests for Subscription Webhook Ingestion Router.
100% offline and deterministic.
"""

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

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


def test_subscription_pending_creates_case_and_executes_action(client):
    """Verify subscription.pending ingests failed charge, generates decision, and executes bounded action."""
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    payload = make_subscription_pending_payload(
        subscription_id="sub_test_p1",
        customer_id="cust_p1",
        amount_paise=299900,
        auth_attempts=1,
        invoice_id="inv_p1",
        event_id="evt_pending_001",
    )
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(body_bytes, settings.razorpay_webhook_secret)

    resp = client.post(
        "/api/v1/webhooks/razorpay",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": "evt_pending_001",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"
    assert data["event"] == "subscription.pending"
    assert data["subscription_id"] == "sub_test_p1"
    assert "case_id" in data

    # Verify repository state
    repo = operations_service.repository
    sub = repo.get_subscription("sub_test_p1")
    assert sub is not None
    assert sub.status == RazorpaySubscriptionStatus.PENDING

    case = repo.get_case_by_billing_cycle("sub_test_p1", "inv_p1")
    assert case is not None
    assert case.is_subscription is True
    assert case.amount_paise == 299900


def test_subscription_charged_reconciles_open_case_as_provider_auto_retry(client):
    """Verify subscription.charged reconciles open case as provider_auto_retry when recovered without payment link."""
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    repo = operations_service.repository

    # 1. Trigger subscription.pending to create open case and action
    p_payload = make_subscription_pending_payload(
        subscription_id="sub_test_c1",
        customer_id="cust_c1",
        amount_paise=199900,
        invoice_id="inv_c1",
        event_id="evt_pending_002",
    )
    p_bytes = json.dumps(p_payload).encode("utf-8")
    client.post(
        "/api/v1/webhooks/razorpay",
        content=p_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": compute_signature(p_bytes, settings.razorpay_webhook_secret),
            "X-Razorpay-Event-Id": "evt_pending_002",
        },
    )

    # 2. Trigger subscription.charged (auto-retry by Razorpay)
    c_payload = make_subscription_charged_payload(
        subscription_id="sub_test_c1",
        customer_id="cust_c1",
        amount_paise=199900,
        invoice_id="inv_c1",
        event_id="evt_charged_002",
    )
    c_bytes = json.dumps(c_payload).encode("utf-8")
    resp = client.post(
        "/api/v1/webhooks/razorpay",
        content=c_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": compute_signature(c_bytes, settings.razorpay_webhook_secret),
            "X-Razorpay-Event-Id": "evt_charged_002",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"

    # Verify case resolved
    case = repo.get_case_by_billing_cycle("sub_test_c1", "inv_c1")
    assert case.current_state == CaseState.RECOVERED
    assert case.outcome_status == OutcomeStatus.RECOVERED
    assert case.resolution_source == RecoveryResolutionSource.PROVIDER_AUTO_RETRY.value


def test_subscription_charged_reconciles_as_recoverai_intervention_when_link_paid(client):
    """Verify subscription.charged attributes to recoverai_intervention when RecoverAI action note is present."""
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    repo = operations_service.repository

    # 1. Trigger subscription.pending
    p_payload = make_subscription_pending_payload(
        subscription_id="sub_test_c2",
        customer_id="cust_c2",
        amount_paise=499900,
        invoice_id="inv_c2",
        event_id="evt_pending_003",
    )
    p_bytes = json.dumps(p_payload).encode("utf-8")
    client.post(
        "/api/v1/webhooks/razorpay",
        content=p_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": compute_signature(p_bytes, settings.razorpay_webhook_secret),
            "X-Razorpay-Event-Id": "evt_pending_003",
        },
    )

    case = repo.get_case_by_billing_cycle("sub_test_c2", "inv_c2")
    action_id = case.last_action_id

    # 2. Trigger subscription.charged with action_id in payment note
    c_payload = make_subscription_charged_payload(
        subscription_id="sub_test_c2",
        customer_id="cust_c2",
        amount_paise=499900,
        invoice_id="inv_c2",
        action_id=action_id,
        is_payment_link=True,
        event_id="evt_charged_003",
    )
    c_bytes = json.dumps(c_payload).encode("utf-8")
    resp = client.post(
        "/api/v1/webhooks/razorpay",
        content=c_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": compute_signature(c_bytes, settings.razorpay_webhook_secret),
            "X-Razorpay-Event-Id": "evt_charged_003",
        },
    )
    assert resp.status_code == 200

    case_after = repo.get_case_by_billing_cycle("sub_test_c2", "inv_c2")
    assert case_after.current_state == CaseState.RECOVERED
    assert case_after.resolution_source == RecoveryResolutionSource.RECOVERAI_INTERVENTION.value


def test_subscription_halted_evaluates_with_high_retry_count(client):
    """Verify subscription.halted sets charge_attempt_count >= 2 and evaluates policy."""
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    repo = operations_service.repository

    payload = make_subscription_halted_payload(
        subscription_id="sub_test_h1",
        customer_id="cust_h1",
        amount_paise=799900,
        auth_attempts=3,
        invoice_id="inv_h1",
        event_id="evt_halted_001",
    )
    body_bytes = json.dumps(payload).encode("utf-8")
    resp = client.post(
        "/api/v1/webhooks/razorpay",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": compute_signature(body_bytes, settings.razorpay_webhook_secret),
            "X-Razorpay-Event-Id": "evt_halted_001",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"
    assert data["event"] == "subscription.halted"

    sub = repo.get_subscription("sub_test_h1")
    assert sub.status == RazorpaySubscriptionStatus.HALTED
    assert sub.charge_attempt_count >= 2

    case = repo.get_case_by_billing_cycle("sub_test_h1", "inv_h1")
    assert case.retry_count >= 2
    assert case.recovery_source == "subscription_halted"


def test_subscription_lifecycle_events(client):
    """Verify activated, cancelled, and completed subscription lifecycle events."""
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    repo = operations_service.repository

    # 1. Activated
    act_payload = make_subscription_lifecycle_payload("subscription.activated", "sub_life_001", status="active", event_id="evt_act_001")
    act_bytes = json.dumps(act_payload).encode("utf-8")
    resp1 = client.post(
        "/api/v1/webhooks/razorpay",
        content=act_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": compute_signature(act_bytes, settings.razorpay_webhook_secret),
            "X-Razorpay-Event-Id": "evt_act_001",
        },
    )
    assert resp1.status_code == 200
    assert repo.get_subscription("sub_life_001").status == RazorpaySubscriptionStatus.ACTIVE

    # 2. Cancelled
    canc_payload = make_subscription_lifecycle_payload("subscription.cancelled", "sub_life_001", status="cancelled", event_id="evt_canc_001")
    canc_bytes = json.dumps(canc_payload).encode("utf-8")
    resp2 = client.post(
        "/api/v1/webhooks/razorpay",
        content=canc_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": compute_signature(canc_bytes, settings.razorpay_webhook_secret),
            "X-Razorpay-Event-Id": "evt_canc_001",
        },
    )
    assert resp2.status_code == 200
    assert repo.get_subscription("sub_life_001").status == RazorpaySubscriptionStatus.CANCELLED


def test_subscription_webhook_deduplication(client):
    """Verify duplicate event IDs are idempotently ignored with HTTP 200."""
    settings.razorpay_webhook_secret = "test_sub_secret_123"
    payload = make_subscription_pending_payload(
        subscription_id="sub_dup_001",
        event_id="evt_dup_001",
    )
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(body_bytes, settings.razorpay_webhook_secret)

    # First delivery
    resp1 = client.post(
        "/api/v1/webhooks/razorpay",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_dup_001"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "processed"

    # Second delivery (replay)
    resp2 = client.post(
        "/api/v1/webhooks/razorpay",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_dup_001"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "ignored"
    assert resp2.json()["reason"] == "duplicate_event"
