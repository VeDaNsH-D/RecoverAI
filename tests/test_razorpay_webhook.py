"""
Unit and integration tests for Razorpay Webhook ingestion and Sync reconciliation endpoints.
100% offline & deterministic.
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
from recovery.models import (
    ActionExecutionStatus,
    ActionRecord,
    CaseState,
    DecisionRecord,
    RecoveryAction,
    RecoveryCaseRecord,
)
from recovery.providers.razorpay.schemas import RazorpayPaymentLinkResponse


from recovery.repository import RecoveryRepository


@pytest.fixture
def client():
    test_repo = RecoveryRepository(db_path=":memory:")
    operations_service.repository = test_repo
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def compute_signature(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def test_webhook_invalid_signature_rejected(client):
    """Verify that webhooks with invalid HMAC-SHA256 signatures are rejected with HTTP 400."""
    settings.razorpay_webhook_secret = "test_webhook_secret_123"

    payload = {"event": "payment_link.paid", "id": "evt_test_001"}
    body_bytes = json.dumps(payload).encode("utf-8")

    resp = client.post(
        "/api/v1/webhooks/razorpay",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": "invalid_signature_hex_code",
            "X-Razorpay-Event-Id": "evt_test_001",
        },
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "INVALID_SIGNATURE" in str(data)


def test_webhook_payment_link_paid_transitions_case_to_recovered(client):
    """Verify payment_link.paid webhook transitions associated case to RECOVERED in integer paise."""
    settings.razorpay_webhook_secret = "test_webhook_secret_123"
    repo = operations_service.repository

    # 1. Setup existing case, decision, and executed action with provider_reference
    case_rec = RecoveryCaseRecord(
        case_id="case_webhook_001",
        customer_id="cust_wh_001",
        amount_paise=550000,
        current_state=CaseState.ACTION_EXECUTED,
        decision_id="dec_wh_001",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        last_action_id="act_wh_001",
        last_action_status="EXECUTED",
        created_at="2026-08-28T12:00:00Z",
        updated_at="2026-08-28T12:00:00Z",
    )
    dec_rec = DecisionRecord(
        decision_id="dec_wh_001",
        case_id="case_webhook_001",
        customer_id="cust_wh_001",
        amount_paise=550000,
        recommended_action=RecoveryAction.PAYMENT_LINK,
        recommended_action_recovery_probability=0.8,
        expected_gross_recovery_paise=440000,
        action_cost_paise=1000,
        expected_net_recovery_paise=439000,
        decision_margin_paise=100000,
        explanation="Webhook test",
        model_family="logistic_regression",
        feature_version="v1.0",
        created_at="2026-08-28T12:00:00Z",
    )
    act_rec = ActionRecord(
        action_id="act_wh_001",
        decision_id="dec_wh_001",
        case_id="case_webhook_001",
        action=RecoveryAction.PAYMENT_LINK,
        idempotency_key="idemp_wh_001",
        payload_hash="hash_wh_001",
        status=ActionExecutionStatus.EXECUTED,
        cost_paise=1000,
        provider_reference="plink_WH_PAID_123",
        error_message=None,
        executed_at="2026-08-28T12:00:00Z",
    )
    repo.save_decision(dec_rec)
    repo.record_action_execution(act_rec, CaseState.ACTION_EXECUTED)

    # 2. Dispatch payment_link.paid webhook
    payload = {
        "entity": "event",
        "event": "payment_link.paid",
        "id": "evt_wh_paid_999",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_WH_PAID_123",
                    "amount": 550000,
                    "amount_paid": 550000,
                    "status": "paid",
                }
            }
        },
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(body_bytes, settings.razorpay_webhook_secret)

    resp = client.post(
        "/api/v1/webhooks/razorpay",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": "evt_wh_paid_999",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"
    assert data["case_id"] == "case_webhook_001"

    # 3. Verify case transitioned to RECOVERED in SQLite
    updated_case = repo.get_case("case_webhook_001")
    assert updated_case is not None
    assert updated_case.current_state == CaseState.RECOVERED
    assert updated_case.outcome_status == "recovered"
    assert updated_case.recovered_amount_paise == 550000

    # 4. Verify durable deduplication: sending identical event returns ignored
    resp_dup = client.post(
        "/api/v1/webhooks/razorpay",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": "evt_wh_paid_999",
        },
    )
    assert resp_dup.status_code == 200
    assert resp_dup.json()["status"] == "ignored"
    assert resp_dup.json()["reason"] == "duplicate_event"


def test_webhook_payment_link_expired_transitions_case_to_not_recovered(client):
    """Verify payment_link.expired webhook transitions associated case to NOT_RECOVERED with 0 paise."""
    settings.razorpay_webhook_secret = "test_webhook_secret_123"
    repo = operations_service.repository

    case_rec = RecoveryCaseRecord(
        case_id="case_webhook_002",
        customer_id="cust_wh_002",
        amount_paise=300000,
        current_state=CaseState.ACTION_EXECUTED,
        decision_id="dec_wh_002",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        created_at="2026-08-28T12:00:00Z",
        updated_at="2026-08-28T12:00:00Z",
    )
    dec_rec = DecisionRecord(
        decision_id="dec_wh_002",
        case_id="case_webhook_002",
        customer_id="cust_wh_002",
        amount_paise=300000,
        recommended_action=RecoveryAction.PAYMENT_LINK,
        recommended_action_recovery_probability=0.6,
        expected_gross_recovery_paise=180000,
        action_cost_paise=1000,
        expected_net_recovery_paise=179000,
        decision_margin_paise=50000,
        explanation="Expire test",
        model_family="logistic_regression",
        feature_version="v1.0",
        created_at="2026-08-28T12:00:00Z",
    )
    act_rec = ActionRecord(
        action_id="act_wh_002",
        decision_id="dec_wh_002",
        case_id="case_webhook_002",
        action=RecoveryAction.PAYMENT_LINK,
        idempotency_key="idemp_wh_002",
        payload_hash="hash_wh_002",
        status=ActionExecutionStatus.EXECUTED,
        cost_paise=1000,
        provider_reference="plink_WH_EXPIRED_456",
        error_message=None,
        executed_at="2026-08-28T12:00:00Z",
    )
    repo.save_decision(dec_rec)
    repo.record_action_execution(act_rec, CaseState.ACTION_EXECUTED)

    payload = {
        "event": "payment_link.expired",
        "id": "evt_wh_expired_888",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_WH_EXPIRED_456",
                    "amount": 300000,
                    "status": "expired",
                }
            }
        },
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(body_bytes, settings.razorpay_webhook_secret)

    resp = client.post(
        "/api/v1/webhooks/razorpay",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": "evt_wh_expired_888",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"

    updated_case = repo.get_case("case_webhook_002")
    assert updated_case is not None
    assert updated_case.current_state == CaseState.NOT_RECOVERED
    assert updated_case.outcome_status == "not_recovered"
    assert updated_case.recovered_amount_paise == 0


def test_provider_sync_endpoint_reconciliation(client):
    """Verify POST /api/v1/recovery/providers/razorpay/sync actively polls Razorpay and settles state."""
    repo = operations_service.repository

    case_rec = RecoveryCaseRecord(
        case_id="case_sync_001",
        customer_id="cust_sync_001",
        amount_paise=800000,
        current_state=CaseState.ACTION_EXECUTED,
        decision_id="dec_sync_001",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        created_at="2026-08-28T12:00:00Z",
        updated_at="2026-08-28T12:00:00Z",
    )
    dec_rec = DecisionRecord(
        decision_id="dec_sync_001",
        case_id="case_sync_001",
        customer_id="cust_sync_001",
        amount_paise=800000,
        recommended_action=RecoveryAction.PAYMENT_LINK,
        recommended_action_recovery_probability=0.85,
        expected_gross_recovery_paise=680000,
        action_cost_paise=1000,
        expected_net_recovery_paise=679000,
        decision_margin_paise=300000,
        explanation="Sync test",
        model_family="logistic_regression",
        feature_version="v1.0",
        created_at="2026-08-28T12:00:00Z",
    )
    act_rec = ActionRecord(
        action_id="act_sync_001",
        decision_id="dec_sync_001",
        case_id="case_sync_001",
        action=RecoveryAction.PAYMENT_LINK,
        idempotency_key="idemp_sync_001",
        payload_hash="hash_sync_001",
        status=ActionExecutionStatus.EXECUTED,
        cost_paise=1000,
        provider_reference="plink_SYNC_PAID_789",
        error_message=None,
        executed_at="2026-08-28T12:00:00Z",
    )
    repo.save_decision(dec_rec)
    repo.record_action_execution(act_rec, CaseState.ACTION_EXECUTED)

    # Mock RazorpayClient.get_payment_link returning paid
    mock_link_resp = RazorpayPaymentLinkResponse(
        id="plink_SYNC_PAID_789",
        short_url="https://rzp.io/i/SyncPaid",
        status="paid",
        amount=800000,
        amount_paid=800000,
        currency="INR",
        reference_id="rec_case_sync_001",
    )

    with patch("recovery.providers.razorpay.client.RazorpayClient.get_payment_link", return_value=mock_link_resp):
        resp = client.post(
            "/api/v1/recovery/providers/razorpay/sync",
            json={"action_id": "act_sync_001"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_status"] == "paid"
        assert data["operational_state"] == "RECOVERED"
        assert data["amount_paid_paise"] == 800000

    updated_case = repo.get_case("case_sync_001")
    assert updated_case.current_state == CaseState.RECOVERED
    assert updated_case.outcome_status == "recovered"


def test_webhook_retry_safety_after_transient_failure(client):
    """Verify that a transient error during outcome processing returns 500 and does NOT suppress future retries."""
    settings.razorpay_webhook_secret = "test_webhook_secret_retry"
    repo = operations_service.repository

    case_rec = RecoveryCaseRecord(
        case_id="case_retry_001",
        customer_id="cust_retry_001",
        amount_paise=400000,
        current_state=CaseState.ACTION_EXECUTED,
        decision_id="dec_retry_001",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        created_at="2026-08-28T12:00:00Z",
        updated_at="2026-08-28T12:00:00Z",
    )
    dec_rec = DecisionRecord(
        decision_id="dec_retry_001",
        case_id="case_retry_001",
        customer_id="cust_retry_001",
        amount_paise=400000,
        recommended_action=RecoveryAction.PAYMENT_LINK,
        recommended_action_recovery_probability=0.75,
        expected_gross_recovery_paise=300000,
        action_cost_paise=1000,
        expected_net_recovery_paise=299000,
        decision_margin_paise=100000,
        explanation="Retry safety test",
        model_family="logistic_regression",
        feature_version="v1.0",
        created_at="2026-08-28T12:00:00Z",
    )
    act_rec = ActionRecord(
        action_id="act_retry_001",
        decision_id="dec_retry_001",
        case_id="case_retry_001",
        action=RecoveryAction.PAYMENT_LINK,
        idempotency_key="idemp_retry_001",
        payload_hash="hash_retry_001",
        status=ActionExecutionStatus.EXECUTED,
        cost_paise=1000,
        provider_reference="plink_RETRY_SAFETY_111",
        error_message=None,
        executed_at="2026-08-28T12:00:00Z",
    )
    repo.save_decision(dec_rec)
    repo.record_action_execution(act_rec, CaseState.ACTION_EXECUTED)

    payload = {
        "event": "payment_link.paid",
        "id": "evt_transient_retry_111",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_RETRY_SAFETY_111",
                    "amount": 400000,
                    "amount_paid": 400000,
                    "status": "paid",
                }
            }
        },
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(body_bytes, settings.razorpay_webhook_secret)

    # 1. Delivery 1: Force transient outcome processing failure
    with patch.object(operations_service, "record_outcome", side_effect=RuntimeError("Simulated DB Lock")):
        resp1 = client.post(
            "/api/v1/webhooks/razorpay",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": sig,
                "X-Razorpay-Event-Id": "evt_transient_retry_111",
            },
        )
        assert resp1.status_code == 500
        err_data = resp1.json()
        assert err_data["error"]["code"] == "PROCESSING_ERROR" or "PROCESSING_ERROR" in str(err_data)
        # Verify raw exception is not exposed to caller
        assert "Simulated DB Lock" not in err_data.get("message", "")

    # Check that case is still in ACTION_EXECUTED state (not transitioned)
    case_state_1 = repo.get_case("case_retry_001")
    assert case_state_1.current_state == CaseState.ACTION_EXECUTED

    # 2. Delivery 2: Webhook retry with identical event_id must NOT be skipped as duplicate
    resp2 = client.post(
        "/api/v1/webhooks/razorpay",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": "evt_transient_retry_111",
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "processed"
    assert resp2.json()["processing_status"] == "processed_recovered"

    # Verify case successfully transitioned to RECOVERED
    case_state_2 = repo.get_case("case_retry_001")
    assert case_state_2.current_state == CaseState.RECOVERED
    assert case_state_2.recovered_amount_paise == 400000

    # 3. Delivery 3: Subsequent duplicate delivery is now properly deduplicated
    resp3 = client.post(
        "/api/v1/webhooks/razorpay",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": "evt_transient_retry_111",
        },
    )
    assert resp3.status_code == 200
    assert resp3.json()["status"] == "ignored"
    assert resp3.json()["reason"] == "duplicate_event"


def test_webhook_already_terminal_case_handling(client):
    """Verify that a webhook for an already settled case returns 200 OK with already_settled reason."""
    settings.razorpay_webhook_secret = "test_webhook_secret_terminal"
    repo = operations_service.repository

    case_rec = RecoveryCaseRecord(
        case_id="case_already_term",
        customer_id="cust_term_001",
        amount_paise=250000,
        current_state=CaseState.ACTION_EXECUTED,
        decision_id="dec_term_001",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        created_at="2026-08-28T12:00:00Z",
        updated_at="2026-08-28T12:00:00Z",
    )
    dec_rec = DecisionRecord(
        decision_id="dec_term_001",
        case_id="case_already_term",
        customer_id="cust_term_001",
        amount_paise=250000,
        recommended_action=RecoveryAction.PAYMENT_LINK,
        recommended_action_recovery_probability=0.7,
        expected_gross_recovery_paise=175000,
        action_cost_paise=1000,
        expected_net_recovery_paise=174000,
        decision_margin_paise=50000,
        explanation="Terminal test",
        model_family="logistic_regression",
        feature_version="v1.0",
        created_at="2026-08-28T12:00:00Z",
    )
    act_rec = ActionRecord(
        action_id="act_term_001",
        decision_id="dec_term_001",
        case_id="case_already_term",
        action=RecoveryAction.PAYMENT_LINK,
        idempotency_key="idemp_term_001",
        payload_hash="hash_term_001",
        status=ActionExecutionStatus.EXECUTED,
        cost_paise=1000,
        provider_reference="plink_ALREADY_SETTLED_222",
        error_message=None,
        executed_at="2026-08-28T12:00:00Z",
    )
    repo.save_decision(dec_rec)
    repo.record_action_execution(act_rec, CaseState.ACTION_EXECUTED)

    # Manually transition case to RECOVERED beforehand
    from api.schemas import OutcomeEventRequest
    from recovery.models import OutcomeStatus
    operations_service.record_outcome(
        OutcomeEventRequest(
            case_id="case_already_term",
            action_id="act_term_001",
            decision_id="dec_term_001",
            outcome_status=OutcomeStatus.RECOVERED,
            recovered_amount_paise=250000,
            provider_reference="plink_ALREADY_SETTLED_222",
        )
    )

    # Now a new webhook event arrives for the already settled action
    payload = {
        "event": "payment_link.paid",
        "id": "evt_new_id_on_already_settled",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_ALREADY_SETTLED_222",
                    "amount": 250000,
                    "amount_paid": 250000,
                    "status": "paid",
                }
            }
        },
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(body_bytes, settings.razorpay_webhook_secret)

    resp = client.post(
        "/api/v1/webhooks/razorpay",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": "evt_new_id_on_already_settled",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert resp.json()["reason"] == "already_settled"

