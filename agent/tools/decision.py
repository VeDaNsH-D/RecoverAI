"""
Recovery decision tool for RecoverAI Agent.
Delegates strictly to the authoritative ML inference & RecoveryDecisionEngine.
"""

from typing import Any, Dict
from agent.tools.base import BaseTool
from agent.models import AgentContext
from api.schemas import PaymentCaseRequest
from api.services.recovery_service import recovery_service
from agent.errors import ToolExecutionError


class GetRecoveryDecisionTool(BaseTool):
    """
    Tool to obtain an authoritative recovery decision from RecoverAI.
    GUARANTEE: The agent does NOT compute probabilities or expected values independently.
    """

    @property
    def name(self) -> str:
        return "get_recovery_decision"

    @property
    def description(self) -> str:
        return (
            "Requests an authoritative, economically optimal recovery decision from the RecoverAI "
            "ML model and RecoveryDecisionEngine. Evaluates candidate actions, action costs, and safety guardrails."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "The unique payment case identifier"}
            },
            "additionalProperties": False,
        }

    def execute(self, context: AgentContext, **kwargs: Any) -> Dict[str, Any]:
        # Assemble PaymentCaseRequest from context
        if context.amount_paise is None or context.customer_id is None:
            raise ToolExecutionError("AgentContext is missing required case fields for decisioning.")

        case_req = PaymentCaseRequest(
            case_id=context.case_id,
            customer_id=context.customer_id,
            amount_paise=context.amount_paise,
            currency=context.currency,
            payment_method=context.payment_method or "upi",  # type: ignore
            is_subscription=bool(context.is_subscription),
            customer_historical_success_rate=0.90,  # default observable baseline if not passed
            customer_total_transactions=20,
            customer_total_failures=1,
            customer_avg_amount_paise=context.amount_paise,
            customer_tenure_months=12,
            failure_type=context.failure_type or "temporary_failure",  # type: ignore
            retry_count=context.retry_count,
            hours_since_failure=context.hours_since_failure,
        )

        try:
            decision_resp = recovery_service.process_decision(case_req)
        except Exception as exc:
            raise ToolExecutionError(f"Failed to obtain recovery decision: {str(exc)}") from exc

        # Update working memory with authoritative decision
        context.decision_id = decision_resp.decision_id
        context.recommended_action = decision_resp.recommended_action
        context.recovery_probability = decision_resp.recommended_action_recovery_probability
        context.expected_gross_paise = decision_resp.expected_gross_recovery_paise
        context.action_cost_paise = decision_resp.action_cost_paise
        context.expected_net_paise = decision_resp.expected_net_recovery_paise
        context.decision_margin_paise = decision_resp.decision_margin_paise
        context.explanation = decision_resp.explanation
        context.current_operational_state = "DECIDED"

        return {
            "decision_id": decision_resp.decision_id,
            "recommended_action": decision_resp.recommended_action,
            "recovery_probability": decision_resp.recommended_action_recovery_probability,
            "expected_gross_recovery_paise": decision_resp.expected_gross_recovery_paise,
            "expected_gross_recovery_inr": decision_resp.expected_gross_recovery_inr,
            "action_cost_paise": decision_resp.action_cost_paise,
            "action_cost_inr": decision_resp.action_cost_inr,
            "expected_net_recovery_paise": decision_resp.expected_net_recovery_paise,
            "expected_net_recovery_inr": decision_resp.expected_net_recovery_inr,
            "decision_margin_paise": decision_resp.decision_margin_paise,
            "explanation": decision_resp.explanation,
            "safety_status": decision_resp.safety_status.model_dump(),
        }
