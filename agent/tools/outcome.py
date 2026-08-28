"""
Outcome recording tool for RecoverAI Agent.
Records observed settlement events and transitions cases to terminal states.
"""

from typing import Any, Dict, Optional
from agent.tools.base import BaseTool
from agent.models import AgentContext
from api.schemas import OutcomeEventRequest
from api.services.operations_service import operations_service
from agent.errors import ToolExecutionError


class RecordRecoveryOutcomeTool(BaseTool):
    """
    Tool to record observed payment settlement outcomes (recovered or not_recovered).
    Transitions the recovery case to a terminal state.
    """

    @property
    def name(self) -> str:
        return "record_recovery_outcome"

    @property
    def description(self) -> str:
        return (
            "Records a terminal payment recovery outcome (recovered or not_recovered) for an executed action. "
            "Updates ledger balances in integer paise."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "Associated payment case ID"},
                "action_id": {"type": "string", "description": "Associated action execution ID"},
                "decision_id": {"type": "string", "description": "Associated decision ID"},
                "outcome_status": {"type": "string", "enum": ["recovered", "not_recovered"]},
                "recovered_amount_paise": {"type": "integer", "minimum": 0},
                "provider_reference": {"type": "string"},
            },
            "required": ["case_id", "action_id", "decision_id", "outcome_status", "recovered_amount_paise"],
            "additionalProperties": False,
        }

    def execute(self, context: AgentContext, **kwargs: Any) -> Dict[str, Any]:
        case_id = kwargs.get("case_id") or context.case_id
        action_id = kwargs.get("action_id") or context.action_id
        decision_id = kwargs.get("decision_id") or context.decision_id
        outcome_status = kwargs.get("outcome_status")
        recovered_amount_paise = kwargs.get("recovered_amount_paise", 0)
        provider_reference = kwargs.get("provider_reference") or context.provider_reference

        if not case_id or not action_id or not decision_id:
            raise ToolExecutionError("Missing required parameters (case_id, action_id, decision_id).")
        if not outcome_status:
            raise ToolExecutionError("Missing required parameter 'outcome_status'.")

        try:
            req = OutcomeEventRequest(
                case_id=case_id,
                action_id=action_id,
                decision_id=decision_id,
                outcome_status=outcome_status,  # type: ignore
                recovered_amount_paise=recovered_amount_paise,
                provider_reference=provider_reference,
            )
            out_resp = operations_service.record_outcome(req)
        except Exception as exc:
            raise ToolExecutionError(f"Failed to record recovery outcome: {str(exc)}") from exc

        # Update context
        context.outcome_status = out_resp.outcome_status.value
        context.recovered_amount_paise = out_resp.recovered_amount_paise
        if out_resp.outcome_status.value == "recovered":
            context.current_operational_state = "RECOVERED"
        else:
            context.current_operational_state = "NOT_RECOVERED"

        return {
            "event_id": out_resp.event_id,
            "case_id": out_resp.case_id,
            "action_id": out_resp.action_id,
            "decision_id": out_resp.decision_id,
            "outcome_status": out_resp.outcome_status.value,
            "recovered_amount_paise": out_resp.recovered_amount_paise,
            "recovered_amount_inr": out_resp.recovered_amount_inr,
            "event_timestamp": out_resp.event_timestamp,
        }
