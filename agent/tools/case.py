"""
Payment case retrieval tool for RecoverAI Agent.
Retrieves observable failed payment context from repository or active context.
"""

from typing import Any, Dict, Optional
from agent.tools.base import BaseTool
from agent.models import AgentContext
from api.services.operations_service import operations_service, CaseNotFoundError
from agent.errors import ToolExecutionError


class GetPaymentCaseTool(BaseTool):
    """
    Tool to retrieve observable payment case attributes.
    GUARANTEE: Zero access to latent simulator variables or ground truth.
    """

    @property
    def name(self) -> str:
        return "get_payment_case"

    @property
    def description(self) -> str:
        return (
            "Retrieves observable context for a failed payment incident, including amount at risk, "
            "payment method, failure type, retry count, and customer history. "
            "Does not expose latent variables or unobservable ground truth."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "The unique payment case identifier"}
            },
            "required": ["case_id"],
            "additionalProperties": False,
        }

    def execute(self, context: AgentContext, **kwargs: Any) -> Dict[str, Any]:
        case_id = kwargs.get("case_id") or context.case_id
        if not case_id:
            raise ToolExecutionError("Missing required parameter 'case_id'.")

        try:
            case_record = operations_service.get_case(case_id)
            context.amount_paise = case_record.amount_paise
            context.customer_id = case_record.customer_id
            context.payment_method = case_record.payment_method
            context.is_subscription = case_record.is_subscription
            context.failure_type = case_record.failure_type
            context.retry_count = case_record.retry_count
            context.current_operational_state = case_record.current_state.value
            context.decision_id = case_record.decision_id
            context.recommended_action = case_record.recommended_action.value
        except CaseNotFoundError:
            # Case not yet persisted in DB (e.g. fresh case request) — use context attributes
            pass

        return {
            "case_id": context.case_id,
            "customer_id": context.customer_id,
            "amount_paise": context.amount_paise,
            "amount_inr": (context.amount_paise / 100.0) if context.amount_paise is not None else None,
            "currency": context.currency,
            "payment_method": context.payment_method,
            "is_subscription": context.is_subscription,
            "failure_type": context.failure_type,
            "retry_count": context.retry_count,
            "hours_since_failure": context.hours_since_failure,
            "current_state": context.current_operational_state,
        }
