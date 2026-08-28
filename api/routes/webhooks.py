"""
Razorpay Webhook Ingestion Router for RecoverAI.
Processes asynchronous payment outcome events with HMAC-SHA256 signature verification and durable deduplication.
"""

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from api.config import settings
from api.schemas import OutcomeEventRequest
from api.services.operations_service import DuplicateOutcomeError, operations_service
from recovery.models import OutcomeStatus
from recovery.repository import RecoveryRepository
from recovery.state_machine import InvalidStateTransitionError

logger = logging.getLogger("recoverai.api.webhooks")
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def verify_razorpay_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    """Verifies HMAC-SHA256 signature using constant-time comparison against raw request bytes."""
    if not signature or not secret:
        return False
    computed_signature = hmac.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed_signature, signature)


@router.post("/razorpay", status_code=status.HTTP_200_OK)
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None, alias="X-Razorpay-Signature"),
    x_razorpay_event_id: Optional[str] = Header(None, alias="X-Razorpay-Event-Id"),
) -> Dict[str, Any]:
    """
    Ingests and processes Razorpay webhook events.
    Verifies HMAC-SHA256 against raw request bytes before JSON deserialization.
    """
    body_bytes = await request.body()

    # 1. Signature Verification
    webhook_secret = settings.razorpay_webhook_secret
    if not webhook_secret:
        logger.error("RAZORPAY_WEBHOOK_SECRET is not configured.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "WEBHOOK_SECRET_NOT_CONFIGURED", "message": "Webhook secret is unconfigured."},
        )

    if not x_razorpay_signature or not verify_razorpay_signature(body_bytes, x_razorpay_signature, webhook_secret):
        logger.warning("Invalid Razorpay webhook signature received.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_SIGNATURE", "message": "HMAC-SHA256 signature verification failed."},
        )

    # 2. Parse Payload safely
    try:
        payload_data = json.loads(body_bytes.decode("utf-8"))
    except Exception as err:
        logger.warning("Malformed webhook JSON payload: %s", str(err))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "MALFORMED_JSON", "message": "Invalid JSON body."},
        )

    event_type = payload_data.get("event", "")
    event_id = x_razorpay_event_id or payload_data.get("id") or f"evt_{hashlib.sha256(body_bytes).hexdigest()[:16]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    repo = operations_service.repository

    # 3. Durable Deduplication
    if repo.is_webhook_event_processed(event_id):
        logger.info("Webhook event '%s' already processed. Returning idempotent 200 OK.", event_id)
        return {"status": "ignored", "reason": "duplicate_event", "event_id": event_id}

    # 4. Extract Target Entity & Provider Reference
    plink_data = payload_data.get("payload", {}).get("payment_link", {}).get("entity", {})
    payment_data = payload_data.get("payload", {}).get("payment", {}).get("entity", {})
    provider_reference = plink_data.get("id") or payment_data.get("description")

    action_record = repo.get_action_by_provider_reference(provider_reference) if provider_reference else None

    # If action record not found by plink id, check notes
    if not action_record:
        notes = plink_data.get("notes", {}) or payment_data.get("notes", {})
        action_id = notes.get("action_id")
        if action_id:
            action_record = repo.get_action(action_id)

    if not action_record:
        logger.info("Webhook event '%s' (%s) unmatched to any RecoverAI action reference.", event_id, event_type)
        repo.save_webhook_event(
            event_id=event_id,
            event_type=event_type,
            provider_reference=provider_reference,
            case_id=None,
            action_id=None,
            processing_status="unmatched",
            payload_json=json.dumps(payload_data),
            processed_at=now_iso,
        )
        return {"status": "unmatched", "event_id": event_id, "event": event_type}

    case_id = action_record.case_id
    action_id = action_record.action_id
    decision_id = action_record.decision_id

    # 5. Process Supported Terminal Events
    try:
        if event_type == "payment_link.paid":
            amount_paid = plink_data.get("amount_paid") or plink_data.get("amount") or action_record.cost_paise
            outcome_req = OutcomeEventRequest(
                case_id=case_id,
                action_id=action_id,
                decision_id=decision_id,
                outcome_status=OutcomeStatus.RECOVERED,
                recovered_amount_paise=int(amount_paid),
                provider_reference=provider_reference or action_record.provider_reference,
            )
            operations_service.record_outcome(outcome_req)
            processing_status = "processed_recovered"

        elif event_type in ("payment_link.expired", "payment_link.cancelled"):
            outcome_req = OutcomeEventRequest(
                case_id=case_id,
                action_id=action_id,
                decision_id=decision_id,
                outcome_status=OutcomeStatus.NOT_RECOVERED,
                recovered_amount_paise=0,
                provider_reference=provider_reference or action_record.provider_reference,
            )
            operations_service.record_outcome(outcome_req)
            processing_status = "processed_not_recovered"

        else:
            processing_status = "ignored_non_terminal"

        repo.save_webhook_event(
            event_id=event_id,
            event_type=event_type,
            provider_reference=provider_reference,
            case_id=case_id,
            action_id=action_id,
            processing_status=processing_status,
            payload_json=json.dumps(payload_data),
            processed_at=now_iso,
        )

        return {
            "status": "processed",
            "event_id": event_id,
            "event": event_type,
            "case_id": case_id,
            "action_id": action_id,
            "processing_status": processing_status,
        }

    except (DuplicateOutcomeError, InvalidStateTransitionError) as terminal_err:
        logger.info(
            "Webhook event '%s' arrived for already terminal / settled action '%s': %s",
            event_id,
            action_id,
            str(terminal_err),
        )
        repo.save_webhook_event(
            event_id=event_id,
            event_type=event_type,
            provider_reference=provider_reference,
            case_id=case_id,
            action_id=action_id,
            processing_status="processed_already_terminal",
            payload_json=json.dumps(payload_data),
            processed_at=now_iso,
        )
        return {
            "status": "ignored",
            "reason": "already_settled",
            "event_id": event_id,
        }

    except Exception as exc:
        logger.error(
            "Unexpected error processing webhook outcome for event '%s': %s",
            event_id,
            str(exc),
            exc_info=True,
        )
        repo.save_webhook_event(
            event_id=event_id,
            event_type=event_type,
            provider_reference=provider_reference,
            case_id=case_id,
            action_id=action_id,
            processing_status=f"error: {str(exc)}",
            payload_json=json.dumps(payload_data),
            processed_at=now_iso,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "PROCESSING_ERROR",
                "message": "Failed to process webhook outcome event. Retryable.",
                "event_id": event_id,
            },
        )
