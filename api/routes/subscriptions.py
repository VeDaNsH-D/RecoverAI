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
from recovery.subscriptions.reconciliation import sync_and_reconcile_subscription

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
    Actively synchronizes subscription state from Razorpay TEST API and reconciles associated open cases
    based on authoritative invoice settlement evidence.
    """
    repo = operations_service.repository
    client = RazorpayClient()

    try:
        sub_record = sync_and_reconcile_subscription(
            subscription_id=req.subscription_id,
            client=client,
            repo=repo,
        )
    except Exception as exc:
        logger.warning("Failed to sync Razorpay subscription '%s': %s", req.subscription_id, str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "GATEWAY_ERROR", "message": f"Could not sync subscription with Razorpay: {str(exc)}"},
        )

    return _subscription_to_response(sub_record)
