"""
Subscription Synchronization tool for RecoverAI Agent.
Allows the agent orchestrator to actively verify and reconcile Razorpay subscription status.
"""

from typing import Any, Dict
from agent.models import AgentContext
from agent.tools.base import BaseTool
from api.schemas import OutcomeEventRequest
from api.services.operations_service import operations_service
from recovery.models import CaseState, OutcomeStatus
from recovery.providers.razorpay.client import RazorpayClient
from recovery.subscriptions.models import RazorpaySubscriptionStatus, RecoveryResolutionSource, SubscriptionRecord
from agent.errors import ToolExecutionError


class SyncSubscriptionTool(BaseTool):
    """
    Tool to query external Razorpay Subscription status and reconcile associated recovery cases.
    """

    @property
    def name(self) -> str:
        return "sync_subscription"

    @property
    def description(self) -> str:
        return (
            "Checks external Razorpay subscription status and reconciles associated billing cycle case. "
            "Can be invoked during subscription recovery workflows."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subscription_id": {"type": "string", "description": "Razorpay sub_xxx subscription ID"},
            },
            "required": ["subscription_id"],
            "additionalProperties": False,
        }

    def execute(self, context: AgentContext, **kwargs: Any) -> Dict[str, Any]:
        subscription_id = kwargs.get("subscription_id")
        if not subscription_id:
            raise ToolExecutionError("Missing required parameter 'subscription_id'.")

        repo = operations_service.repository
        try:
            client = RazorpayClient()
            sub_resp = client.get_subscription(subscription_id)
        except Exception as exc:
            raise ToolExecutionError(f"Failed to query Razorpay subscription: {str(exc)}") from exc

        existing_sub = repo.get_subscription(subscription_id)
        raw_status = sub_resp.status.lower()
        sub_status = None
        for s in RazorpaySubscriptionStatus:
            if s.value == raw_status:
                sub_status = s
                break
        if sub_status is None:
            sub_status = RazorpaySubscriptionStatus.PENDING

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
            created_at=existing_sub.created_at if existing_sub else "2026-09-05T00:00:00Z",
            updated_at="2026-09-05T00:00:00Z",
        )
        repo.save_subscription(sub_record)

        # Settle open case if subscription became active/completed
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
                    context.current_operational_state = "RECOVERED"
                    context.outcome_status = "recovered"
                    context.recovered_amount_paise = case.amount_paise

        return {
            "subscription_id": sub_resp.id,
            "status": sub_status.value,
            "current_cycle": sub_resp.current_count,
            "total_cycles": sub_resp.total_count,
            "auth_attempts": sub_resp.auth_attempts,
            "charge_attempt_count": charge_attempt_count,
            "current_operational_state": context.current_operational_state,
        }
