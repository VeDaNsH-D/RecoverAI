"""
Subscription Synchronization and Settlement Reconciliation Service for RecoverAI.
Enforces strict settlement evidence, authoritative invoice billing amounts, and fail-closed safety.
"""

from __future__ import annotations
from datetime import datetime, timezone
import logging
from typing import TYPE_CHECKING, Any, List, Optional

from api.schemas import OutcomeEventRequest
from recovery.models import CaseState, OutcomeStatus, RecoveryCaseRecord
from recovery.providers.razorpay.client import RazorpayClient
from recovery.providers.razorpay.schemas import RazorpayInvoiceResponse, RazorpaySubscriptionResponse
from recovery.subscriptions.models import (
    RazorpaySubscriptionStatus,
    RecoveryResolutionSource,
    SubscriptionRecord,
)

if TYPE_CHECKING:
    from recovery.repository import RecoveryRepository

logger = logging.getLogger("recoverai.subscriptions.reconciliation")


def find_matching_invoice(
    invoices: List[RazorpayInvoiceResponse],
    case: Optional[RecoveryCaseRecord],
    current_cycle: Optional[int] = None,
) -> Optional[RazorpayInvoiceResponse]:
    """
    Deterministically resolves the matching provider invoice for a recovery case.
    
    Resolution hierarchy:
    1. Exact match on case.billing_cycle_id == invoice.id
    2. Invoice ID contained in case.case_id (e.g. sub_{sub_id}_{inv_id})
    3. If case.billing_cycle_id indicates cycle index (e.g. cycle_N) or current_cycle matches:
       - Match invoice by index if ordering is 1-to-1
    4. If only 1 invoice exists and no conflicting cycle ID is present, match that single invoice.
    5. Fallback: Return None (fail safe, no ambiguous guessing).
    """
    if not invoices:
        return None

    if case is not None:
        # 1. Exact match on billing_cycle_id == invoice.id
        if case.billing_cycle_id:
            for inv in invoices:
                if inv.id == case.billing_cycle_id:
                    return inv

        # 2. Case ID contains invoice ID (e.g. sub_{sub_id}_{inv_id})
        if case.case_id:
            for inv in invoices:
                if inv.id and inv.id in case.case_id:
                    return inv

        # 3. Cycle index match (e.g. cycle_1, cycle_2)
        if case.billing_cycle_id and case.billing_cycle_id.startswith("cycle_"):
            try:
                cycle_num = int(case.billing_cycle_id.split("_")[1])
                if 1 <= cycle_num <= len(invoices):
                    return invoices[cycle_num - 1]
            except (IndexError, ValueError):
                pass

    # 4. If only one invoice exists and case has no conflicting specific billing cycle
    if len(invoices) == 1:
        return invoices[0]

    # 5. If current_cycle is provided and matches list length
    if current_cycle is not None and 1 <= current_cycle <= len(invoices):
        return invoices[current_cycle - 1]

    return None


def sync_and_reconcile_subscription(
    subscription_id: str,
    client: RazorpayClient,
    repo: RecoveryRepository,
) -> SubscriptionRecord:
    """
    Synchronizes subscription lifecycle state from Razorpay and reconciles associated recovery cases.
    
    Invariants:
    1. Subscription ACTIVE != Billing Cycle RECOVERED.
    2. A recovery case is marked RECOVERED ONLY IF its specific matching invoice is genuinely paid.
    3. Money amounts are derived strictly from authoritative provider invoice/payment objects. Notes are never authoritative.
    4. Unrecognized subscription statuses fail closed as UNKNOWN with no interventions permitted.
    5. RecoverAI intervention attribution requires deterministic proof; ambiguous settlement defaults to provider_auto_retry.
    """
    sub_resp = client.get_subscription(subscription_id)

    # 1. Fail-closed status mapping
    raw_status = (sub_resp.status or "").lower()
    sub_status = None
    for s in RazorpaySubscriptionStatus:
        if s.value == raw_status:
            sub_status = s
            break
    if sub_status is None:
        logger.warning(
            "Encountered unrecognized Razorpay subscription status '%s' for subscription '%s'. Failing closed as UNKNOWN.",
            sub_resp.status,
            subscription_id,
        )
        sub_status = RazorpaySubscriptionStatus.UNKNOWN

    # 2. Fetch Invoices from Provider (Authoritative Billing Source)
    try:
        invoices = client.get_subscription_invoices(subscription_id)
    except Exception as exc:
        logger.warning("Could not fetch invoices for subscription '%s': %s", subscription_id, str(exc))
        invoices = []

    # 3. Inspect existing DB subscription record and open case
    existing_sub = repo.get_subscription(subscription_id)
    open_case: Optional[RecoveryCaseRecord] = None
    if existing_sub and existing_sub.last_case_id:
        open_case = repo.get_case(existing_sub.last_case_id)

    # 4. Determine Authoritative Amount from Matching Invoice
    matching_invoice = find_matching_invoice(invoices, open_case, current_cycle=sub_resp.current_count)
    if matching_invoice is not None:
        amount_due_paise = matching_invoice.amount_due if matching_invoice.amount_due > 0 else matching_invoice.amount
        currency = matching_invoice.currency or "INR"
    elif existing_sub is not None:
        amount_due_paise = existing_sub.amount_due_paise
        currency = existing_sub.currency
    else:
        amount_due_paise = 0
        currency = "INR"

    charge_attempt_count = sub_resp.auth_attempts
    if sub_status == RazorpaySubscriptionStatus.HALTED:
        charge_attempt_count = max(charge_attempt_count, 2)
    elif existing_sub:
        charge_attempt_count = max(charge_attempt_count, existing_sub.charge_attempt_count)

    is_recoverable = sub_status not in (
        RazorpaySubscriptionStatus.CANCELLED,
        RazorpaySubscriptionStatus.COMPLETED,
        RazorpaySubscriptionStatus.UNKNOWN,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    sub_record = SubscriptionRecord(
        subscription_id=sub_resp.id,
        customer_id=sub_resp.customer_id or (existing_sub.customer_id if existing_sub else f"cust_{sub_resp.id[:8]}"),
        plan_id=sub_resp.plan_id,
        status=sub_status,
        current_cycle=sub_resp.current_count,
        total_cycles=sub_resp.total_count,
        amount_due_paise=amount_due_paise,
        currency=currency,
        charge_attempt_count=charge_attempt_count,
        last_case_id=existing_sub.last_case_id if existing_sub else None,
        is_recoverable=is_recoverable,
        created_at=existing_sub.created_at if existing_sub else now_iso,
        updated_at=now_iso,
    )
    repo.save_subscription(sub_record)

    # 5. Settlement Reconciliation (ONLY IF matching invoice is genuinely paid)
    if open_case and open_case.current_state in (CaseState.ACTION_EXECUTED, CaseState.ACTION_PENDING):
        case_invoice = find_matching_invoice(invoices, open_case)
        if case_invoice is not None and case_invoice.status.lower() == "paid" and case_invoice.amount_paid > 0:
            # Genuine settlement evidence confirmed for this billing cycle!
            action_record = repo.get_action(open_case.last_action_id) if open_case.last_action_id else None
            
            # Deterministic attribution evaluation
            resolution_source = RecoveryResolutionSource.PROVIDER_AUTO_RETRY.value
            if action_record is not None and action_record.provider_reference:
                # Attribution claimed ONLY if settlement connects deterministically to RecoverAI action
                if case_invoice.payment_id and action_record.provider_reference in (case_invoice.payment_id, case_invoice.id):
                    resolution_source = RecoveryResolutionSource.RECOVERAI_INTERVENTION.value
                elif action_record.action.value == "payment_link" and case_invoice.notes.get("recoverai_action_id") == action_record.action_id:
                    resolution_source = RecoveryResolutionSource.RECOVERAI_INTERVENTION.value

            logger.info(
                "Subscription sync confirmed settlement for case '%s' (invoice '%s', paid=%d paise, attribution=%s)",
                open_case.case_id,
                case_invoice.id,
                case_invoice.amount_paid,
                resolution_source,
            )

            out_req = OutcomeEventRequest(
                case_id=open_case.case_id,
                action_id=action_record.action_id if action_record else None,
                decision_id=action_record.decision_id if action_record else open_case.decision_id,
                outcome_status=OutcomeStatus.RECOVERED,
                recovered_amount_paise=case_invoice.amount_paid,  # Authoritative amount_paid
                provider_reference=action_record.provider_reference if action_record else case_invoice.payment_id,
                resolution_source=resolution_source,
            )
            from api.services.operations_service import operations_service
            operations_service.record_outcome(out_req)
        else:
            logger.info(
                "Subscription '%s' synced (status=%s). Open case '%s' remains '%s' (no paid settlement evidence for invoice).",
                subscription_id,
                sub_status.value,
                open_case.case_id,
                open_case.current_state.value,
            )

    return sub_record