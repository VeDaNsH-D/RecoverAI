"""
Razorpay Provider Synchronization and Reconciliation Router.
Allows active polling / reconciliation of external payment link statuses against RecoverAI lifecycle ledgers.
"""

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from api.schemas import OutcomeEventRequest
from api.services.operations_service import operations_service
from recovery.models import OutcomeStatus
from recovery.providers.razorpay.client import RazorpayClient

logger = logging.getLogger("recoverai.api.provider_sync")
router = APIRouter(prefix="/recovery/providers/razorpay", tags=["Razorpay Sync"])


class RazorpaySyncRequest(BaseModel):
    action_id: str = Field(..., description="Target RecoverAI action ID")
    provider_reference: Optional[str] = Field(default=None, description="Optional payment link reference ID")


@router.post("/sync", status_code=status.HTTP_200_OK)
def sync_razorpay_action_status(req: RazorpaySyncRequest) -> Dict[str, Any]:
    """
    Actively queries Razorpay TEST API to reconcile payment status for an action.
    Transitions case to RECOVERED or NOT_RECOVERED if external terminal state is observed.
    """
    repo = operations_service.repository
    action_record = repo.get_action(req.action_id)
    if not action_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "ACTION_NOT_FOUND", "message": f"Action '{req.action_id}' not found."},
        )

    provider_ref = req.provider_reference or action_record.provider_reference
    if not provider_ref or not provider_ref.startswith("plink_"):
        return {
            "action_id": req.action_id,
            "case_id": action_record.case_id,
            "provider_reference": provider_ref,
            "provider_status": "unsupported",
            "message": "Action does not have a valid Razorpay payment link provider reference.",
        }

    client = RazorpayClient()
    try:
        plink = client.get_payment_link(provider_ref)
    except Exception as exc:
        logger.warning("Failed to fetch Razorpay status for '%s': %s", provider_ref, str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "GATEWAY_ERROR", "message": f"Could not sync with Razorpay: {str(exc)}"},
        )

    case_record = repo.get_case(action_record.case_id)
    current_state = case_record.current_state.value if case_record else "UNKNOWN"

    # Settle if terminal and not already settled
    if current_state not in ("RECOVERED", "NOT_RECOVERED"):
        if plink.status == "paid":
            amount_paid = plink.amount_paid or plink.amount or action_record.cost_paise
            out_req = OutcomeEventRequest(
                case_id=action_record.case_id,
                action_id=action_record.action_id,
                decision_id=action_record.decision_id,
                outcome_status=OutcomeStatus.RECOVERED,
                recovered_amount_paise=int(amount_paid),
                provider_reference=plink.id,
            )
            operations_service.record_outcome(out_req)
            current_state = "RECOVERED"

        elif plink.status in ("expired", "cancelled"):
            out_req = OutcomeEventRequest(
                case_id=action_record.case_id,
                action_id=action_record.action_id,
                decision_id=action_record.decision_id,
                outcome_status=OutcomeStatus.NOT_RECOVERED,
                recovered_amount_paise=0,
                provider_reference=plink.id,
            )
            operations_service.record_outcome(out_req)
            current_state = "NOT_RECOVERED"

    return {
        "action_id": action_record.action_id,
        "case_id": action_record.case_id,
        "decision_id": action_record.decision_id,
        "provider_reference": plink.id,
        "provider_status": plink.status,
        "operational_state": current_state,
        "amount_paise": plink.amount,
        "amount_paid_paise": plink.amount_paid,
        "short_url": plink.short_url,
    }
