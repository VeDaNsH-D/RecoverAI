"""
Razorpay Payment Link Synchronization tool for RecoverAI Agent.
Allows the agent orchestrator to actively verify payment link settlement status.
"""

from typing import Any, Dict
from agent.models import AgentContext
from agent.tools.base import BaseTool
from api.schemas import OutcomeEventRequest
from api.services.operations_service import operations_service
from recovery.models import OutcomeStatus
from recovery.providers.razorpay.client import RazorpayClient
from agent.errors import ToolExecutionError


class SyncRazorpayPaymentLinkTool(BaseTool):
    """
    Tool to check external Razorpay Payment Link status and reconcile operational state.
    """

    @property
    def name(self) -> str:
        return "sync_razorpay_payment_link"

    @property
    def description(self) -> str:
        return (
            "Checks external Razorpay payment link status and reconciles terminal payment settlement. "
            "Only executable after payment_link action has been executed."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "Executed action ID"},
                "case_id": {"type": "string", "description": "Associated case ID"},
                "provider_reference": {"type": "string", "description": "Razorpay plink_xxx ID"},
            },
            "required": ["action_id"],
            "additionalProperties": False,
        }

    def execute(self, context: AgentContext, **kwargs: Any) -> Dict[str, Any]:
        action_id = kwargs.get("action_id") or context.action_id
        if not action_id:
            raise ToolExecutionError("Missing required parameter 'action_id'.")

        repo = operations_service.repository
        action_record = repo.get_action(action_id)
        if not action_record:
            raise ToolExecutionError(f"Action '{action_id}' not found.")

        provider_ref = kwargs.get("provider_reference") or action_record.provider_reference or context.provider_reference
        if not provider_ref or not provider_ref.startswith("plink_"):
            return {
                "action_id": action_id,
                "provider_status": "unsupported",
                "message": "Action does not have a valid Razorpay payment link reference.",
            }

        try:
            client = RazorpayClient()
            plink = client.get_payment_link(provider_ref)
        except Exception as exc:
            raise ToolExecutionError(f"Failed to query Razorpay status: {str(exc)}") from exc

        # Settle if terminal
        if context.current_operational_state not in ("RECOVERED", "NOT_RECOVERED"):
            if plink.status == "paid":
                amount_paid = plink.amount_paid or plink.amount
                out_req = OutcomeEventRequest(
                    case_id=action_record.case_id,
                    action_id=action_record.action_id,
                    decision_id=action_record.decision_id,
                    outcome_status=OutcomeStatus.RECOVERED,
                    recovered_amount_paise=int(amount_paid),
                    provider_reference=plink.id,
                )
                operations_service.record_outcome(out_req)
                context.current_operational_state = "RECOVERED"
                context.outcome_status = "recovered"
                context.recovered_amount_paise = int(amount_paid)

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
                context.current_operational_state = "NOT_RECOVERED"
                context.outcome_status = "not_recovered"
                context.recovered_amount_paise = 0

        return {
            "action_id": action_record.action_id,
            "case_id": action_record.case_id,
            "provider_reference": plink.id,
            "provider_status": plink.status,
            "current_operational_state": context.current_operational_state,
            "amount_paid_paise": plink.amount_paid,
        }
