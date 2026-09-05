from typing import Any, Dict
from agent.models import AgentContext
from agent.tools.base import BaseTool
from api.services.operations_service import operations_service
from recovery.models import CaseState
from recovery.providers.razorpay.client import RazorpayClient
from recovery.subscriptions.reconciliation import sync_and_reconcile_subscription
from agent.errors import ToolExecutionError


class SyncSubscriptionTool(BaseTool):
    """
    Tool to query external Razorpay Subscription status and reconcile associated recovery cases
    using authoritative provider invoice settlement evidence.
    """

    @property
    def name(self) -> str:
        return "sync_subscription"

    @property
    def description(self) -> str:
        return (
            "Checks external Razorpay subscription status and reconciles associated billing cycle case "
            "based on authoritative invoice settlement evidence. Can be invoked during subscription recovery workflows."
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
            sub_record = sync_and_reconcile_subscription(
                subscription_id=subscription_id,
                client=client,
                repo=repo,
            )
        except Exception as exc:
            raise ToolExecutionError(f"Failed to query/sync Razorpay subscription: {str(exc)}") from exc

        # If a case was associated and was transitioned to RECOVERED, update agent context
        if context.case_id:
            case = repo.get_case(context.case_id)
            if case and case.current_state == CaseState.RECOVERED:
                context.current_operational_state = "RECOVERED"
                context.outcome_status = "recovered"
                context.recovered_amount_paise = case.recovered_amount_paise or case.amount_paise

        return {
            "subscription_id": sub_record.subscription_id,
            "status": sub_record.status.value,
            "current_cycle": sub_record.current_cycle,
            "total_cycles": sub_record.total_cycles,
            "amount_due_paise": sub_record.amount_due_paise,
            "charge_attempt_count": sub_record.charge_attempt_count,
            "is_recoverable": sub_record.is_recoverable,
            "current_operational_state": context.current_operational_state,
        }
