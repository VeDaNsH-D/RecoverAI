"""
Recovery action execution tool for RecoverAI Agent.
Dispatches action execution via the operations service and enforces decision consistency.
"""

from typing import Any, Dict
from agent.tools.base import BaseTool
from agent.models import AgentContext
from api.schemas import ActionExecutionRequest
from api.services.operations_service import operations_service
from agent.errors import ActionMismatchError, ToolExecutionError


class ExecuteRecoveryActionTool(BaseTool):
    """
    Tool to dispatch the recommended recovery action to the provider layer.
    GUARANTEE: Strictly enforces that the dispatched action matches the decision recommendation.
    """

    @property
    def name(self) -> str:
        return "execute_recovery_action"

    @property
    def description(self) -> str:
        return (
            "Dispatches the recommended recovery action for execution. "
            "Enforces that the requested action exactly matches the authoritative decision recommendation. "
            "Guarantees persistence-backed idempotency."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "decision_id": {"type": "string", "description": "Associated decision identifier"},
                "action": {"type": "string", "description": "Action to execute (must match recommended_action)"},
                "idempotency_key": {"type": "string", "description": "Unique key to ensure exactly-once execution"},
                "force_failure": {"type": "boolean", "description": "Optional flag to simulate technical provider failure"},
            },
            "required": ["decision_id", "action", "idempotency_key"],
            "additionalProperties": False,
        }

    def execute(self, context: AgentContext, **kwargs: Any) -> Dict[str, Any]:
        decision_id = kwargs.get("decision_id") or context.decision_id
        action = kwargs.get("action") or context.recommended_action
        idempotency_key = kwargs.get("idempotency_key")
        force_failure = kwargs.get("force_failure", False)

        if not decision_id:
            raise ToolExecutionError("Missing required parameter 'decision_id'.")
        if not action:
            raise ToolExecutionError("Missing required parameter 'action'.")
        if not idempotency_key:
            raise ToolExecutionError("Missing required parameter 'idempotency_key'.")

        # NON-NEGOTIABLE SAFETY CHECK: Ensure action matches decision recommendation
        if context.recommended_action and action != context.recommended_action:
            raise ActionMismatchError(
                f"Cannot execute '{action}': Authoritative decision recommended '{context.recommended_action}'. "
                "Action substitution is strictly forbidden."
            )

        try:
            req = ActionExecutionRequest(
                decision_id=decision_id,
                action=action,  # type: ignore
                idempotency_key=idempotency_key,
                merchant_reference=f"agent_ref_{context.case_id}",
                force_failure=force_failure,
            )
            act_resp = operations_service.execute_action(req)
        except Exception as exc:
            raise ToolExecutionError(f"Action execution dispatch failed: {str(exc)}") from exc

        # Update context
        context.action_id = act_resp.action_id
        context.execution_status = act_resp.status.value
        context.provider_reference = act_resp.provider_reference
        if act_resp.status.value == "EXECUTED":
            context.current_operational_state = "ACTION_EXECUTED"
        elif act_resp.status.value == "FAILED":
            context.current_operational_state = "EXECUTION_FAILED"

        return {
            "action_id": act_resp.action_id,
            "decision_id": act_resp.decision_id,
            "case_id": act_resp.case_id,
            "action": act_resp.action.value,
            "status": act_resp.status.value,
            "cost_paise": act_resp.cost_paise,
            "cost_inr": act_resp.cost_inr,
            "provider_reference": act_resp.provider_reference,
            "error_message": act_resp.error_message,
            "executed_at": act_resp.executed_at,
        }
