"""
Subscription Recovery and Synchronization Router for RecoverAI.
Provides endpoints to query subscription records and actively synchronize lifecycle states with Razorpay.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status

from api.schemas import OutcomeEventRequest, SubscriptionResponse, SubscriptionSyncRequest
from api.services.operations_service import operations_service
from recovery.models import CaseState, OutcomeStatus
from recovery.providers.razorpay.client import RazorpayClient
from recovery.subscriptions.models import (
    RazorpaySubscriptionStatus,
    RecoveryResolutionSource,
    SubscriptionRecord,
)

logger = logging.getLogger("recoverai.api.subscriptions")
router = APIRouter(prefix="/recovery/subscriptions", tags=["Subscriptions"])


def _subscription_to_response(sub: SubscriptionRecord) -> SubscriptionResponse:
    """Converts a SubscriptionRecord domain object to SubscriptionResponse schema."""
    return SubscriptionResponse(
        subscription_id=sub.subscription_id,
        customer_id=sub.customer_id,
        plan_id=sub.plan_id,
        status=sub.status.value,
        current_cycle=sub.current_cycle,
        total_cycles=sub.total_cycles,
        amount_due_paise=sub.amount_due_paise,
        amount_due_inr=sub.amount_due_paise / 100.0,
        currency=sub.currency,
        charge_attempt_count=sub.charge_attempt_count,
        next_charge_at=sub.next_charge_at,
        last_case_id=sub.last_case_id,
        is_recoverable=sub.is_recoverable,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
    )


@router.get("/{subscription_id}", response_model=SubscriptionResponse, status_code=status.HTTP_200_OK)
def get_subscription(subscription_id: str) -> SubscriptionResponse:
    """
    Retrieves the current subscription state by subscription ID.
    """
    repo = operations_service.repository
    sub = repo.get_subscription(subscription_id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "SUBSCRIPTION_NOT_FOUND", "message": f"Subscription '{subscription_id}' not found."},
        )
    return _subscription_to_response(sub)


@router.get("", response_model=List[SubscriptionResponse], status_code=status.HTTP_200_OK)
def list_subscriptions(
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (active, pending, halted, etc.)"),
    limit: int = Query(default=50, ge=1, le=200, description="Max records to return"),
) -> List[SubscriptionResponse]:
    """
    Lists subscriptions with optional status filtering.
    """
    repo = operations_service.repository
    subscriptions = repo.list_subscriptions(status_filter=status_filter, limit=limit)
    return [_subscription_to_response(s) for s in subscriptions]


@router.post("/sync", response_model=SubscriptionResponse, status_code=status.HTTP_200_OK)
def sync_subscription(req: SubscriptionSyncRequest) -> SubscriptionResponse:
    """
    Actively synchronizes subscription state from Razorpay TEST API and reconciles associated open cases.
    """
    repo = operations_service.repository
    client = RazorpayClient()

    try:
        sub_resp = client.get_subscription(req.subscription_id)
    except Exception as exc:
        logger.warning("Failed to fetch Razorpay subscription '%s': %s", req.subscription_id, str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "GATEWAY_ERROR", "message": f"Could not sync subscription with Razorpay: {str(exc)}"},
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    raw_status = sub_resp.status.lower()
    sub_status = None
    for s in RazorpaySubscriptionStatus:
        if s.value == raw_status:
            sub_status = s
            break
    if sub_status is None:
        sub_status = RazorpaySubscriptionStatus.PENDING

    # Check existing subscription in DB
    existing_sub = repo.get_subscription(req.subscription_id)
    charge_attempt_count = sub_resp.auth_attempts
    if sub_status == RazorpaySubscriptionStatus.HALTED:
        charge_attempt_count = max(charge_attempt_count, 2)
    elif existing_sub:
        charge_attempt_count = max(charge_attempt_count, existing_sub.charge_attempt_count)

    sub_record = SubscriptionRecord(
        subscription_id=sub_resp.id,
        customer_id=sub_resp.customer_id or (existing_sub.customer_id if existing_sub else f"cust_{sub_resp.id[:8]}"),
        plan_id=sub_resp.plan_id,
        status=sub_status,
        current_cycle=sub_resp.current_count,
        total_cycles=sub_resp.total_count,
        amount_due_paise=sub_resp.notes.get("amount_paise", existing_sub.amount_due_paise if existing_sub else 0),
        currency=sub_resp.notes.get("currency", "INR"),
        charge_attempt_count=charge_attempt_count,
        last_case_id=existing_sub.last_case_id if existing_sub else None,
        created_at=existing_sub.created_at if existing_sub else now_iso,
        updated_at=now_iso,
    )
    repo.save_subscription(sub_record)

    # Reconcile open cases if subscription is resolved
    if sub_status in (RazorpaySubscriptionStatus.ACTIVE, RazorpaySubscriptionStatus.COMPLETED) and existing_sub and existing_sub.last_case_id:
        case = repo.get_case(existing_sub.last_case_id)
        if case and case.current_state in (CaseState.ACTION_EXECUTED, CaseState.ACTION_PENDING):
            action_record = repo.get_action(case.last_action_id) if case.last_action_id else None
            if action_record:
                out_req = OutcomeEventRequest(
                    case_id=case.case_id,
                    action_id=action_record.action_id,
                    decision_id=action_record.decision_id,
                    outcome_status=OutcomeStatus.RECOVERED,
                    recovered_amount_paise=case.amount_paise,
                    provider_reference=action_record.provider_reference,
                    resolution_source=RecoveryResolutionSource.PROVIDER_AUTO_RETRY.value,
                )
                operations_service.record_outcome(out_req)

    return _subscription_to_response(sub_record)
