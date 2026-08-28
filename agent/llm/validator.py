"""
Semantic tool-call validator for RecoverAI LLM Agent.
Enforces hard domain constraints, action authority, lifecycle rules, and explicit failure classification.
"""

from typing import Any, Dict, Optional
from agent.models import AgentContext
from agent.tools.registry import ToolRegistry, default_tool_registry
from agent.llm.base import FailureCategory, LLMToolCall


class ToolValidationError(Exception):
    """Base exception for semantic tool validation failures."""
    def __init__(self, message: str, category: FailureCategory):
        super().__init__(message)
        self.category = category


def _norm_action(act: Any) -> str:
    if act is None:
        return ""
    if hasattr(act, "value"):
        return str(act.value).lower()
    val = str(act).lower()
    if val.startswith("recoveryaction."):
        val = val.split(".", 1)[1]
    return val


class ToolCallValidator:
    """
    Validates LLM-generated tool calls against approved tools, schemas, and lifecycle constraints.
    """

    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        self.tool_registry = tool_registry or default_tool_registry

    def validate_tool_call(self, tool_call: LLMToolCall, context: AgentContext) -> None:
        """
        Performs structural and semantic validation on an incoming LLM tool call.
        Raises ToolValidationError with explicit FailureCategory on any violation.
        """
        tool_name = tool_call.tool
        args = tool_call.arguments

        # 1. Verify Tool Exists in Approved Registry
        tool = self.tool_registry.get(tool_name)
        if not tool:
            raise ToolValidationError(
                f"Unknown or unapproved tool '{tool_name}'. Allowed tools: {list(self.tool_registry._tools.keys())}",
                category=FailureCategory.INVALID_TOOL_CALL,
            )

        # 2. Semantic Validation: Action Execution Authority
        if tool_name == "execute_recovery_action":
            req_action = args.get("action")
            dec_id = args.get("decision_id")

            # Check decision presence
            if not context.decision_id and not dec_id:
                raise ToolValidationError(
                    "Cannot execute recovery action before obtaining an authoritative decision.",
                    category=FailureCategory.POLICY_VIOLATION,
                )

            # Enforce exact match with recommended action
            if context.recommended_action and req_action:
                norm_req = _norm_action(req_action)
                norm_rec = _norm_action(context.recommended_action)
                if norm_req != norm_rec:
                    raise ToolValidationError(
                        f"Action substitution rejected: Attempted to execute '{req_action}' "
                        f"when authoritative decision recommended '{context.recommended_action}'.",
                        category=FailureCategory.POLICY_VIOLATION,
                    )

            # Prevent duplicate execution on already executed action
            if context.current_operational_state == "ACTION_EXECUTED":
                raise ToolValidationError(
                    "Action has already been executed for this case. Repeated execution is forbidden.",
                    category=FailureCategory.POLICY_VIOLATION,
                )

        # 3. Semantic Validation: Outcome Recording Lifecycle
        elif tool_name == "record_recovery_outcome":
            if context.current_operational_state not in ("ACTION_EXECUTED", "RECOVERED", "NOT_RECOVERED"):
                raise ToolValidationError(
                    f"Cannot record outcome in current state '{context.current_operational_state}'. "
                    "Action must be in ACTION_EXECUTED state before recording outcome.",
                    category=FailureCategory.POLICY_VIOLATION,
                )

    def validate_workflow_completion(self, context: AgentContext) -> None:
        """
        Verifies whether the agent reached a legitimate domain completion state.
        Raises ToolValidationError(category=FailureCategory.WORKFLOW_FAILURE) if LLM stopped prematurely.
        """
        terminal_states = {"ACTION_EXECUTED", "EXECUTION_FAILED", "RECOVERED", "NOT_RECOVERED"}
        current = context.current_operational_state

        # If decision recommended no_action and action was executed, that's terminal
        if current in terminal_states:
            return

        # If workflow has not dispatched action or obtained decision, premature stop is a failure
        raise ToolValidationError(
            f"Premature workflow termination: Agent stopped in non-terminal state '{current or 'STARTED'}'. "
            "Workflow requires decisioning and action execution.",
            category=FailureCategory.WORKFLOW_FAILURE,
        )


# Global default validator
default_tool_validator = ToolCallValidator()
