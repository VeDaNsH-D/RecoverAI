"""
Action execution status query tool for RecoverAI Agent.
"""

from typing import Any, Dict
from agent.tools.base import BaseTool
from agent.models import AgentContext
from api.services.operations_service import operations_service
from agent.errors import ToolExecutionError


class GetActionStatusTool(BaseTool):
    """
    Tool to inspect the status and details of a previously executed recovery action.
    """

    @property
    def name(self) -> str:
        return "get_action_status"

    @property
    def description(self) -> str:
        return "Queries the execution status, provider reference, and operational cost of a specific action execution ID."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "The unique action execution identifier"}
            },
            "required": ["action_id"],
            "additionalProperties": False,
        }

    def execute(self, context: AgentContext, **kwargs: Any) -> Dict[str, Any]:
        action_id = kwargs.get("action_id") or context.action_id
        if not action_id:
            raise ToolExecutionError("Missing required parameter 'action_id'.")

        try:
            act = operations_service.get_action(action_id)
        except Exception as exc:
            raise ToolExecutionError(f"Failed to retrieve action record: {str(exc)}") from exc

        return {
            "action_id": act.action_id,
            "decision_id": act.decision_id,
            "case_id": act.case_id,
            "action": act.action.value,
            "status": act.status.value,
            "cost_paise": act.cost_paise,
            "cost_inr": act.cost_inr,
            "provider_reference": act.provider_reference,
            "error_message": act.error_message,
            "executed_at": act.executed_at,
        }
