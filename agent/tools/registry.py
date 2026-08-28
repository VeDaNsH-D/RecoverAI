"""
Tool Registry for RecoverAI Agent.
Coordinates available recovery tools and exposes structured tool definitions.
"""

from typing import Any, Dict, List, Optional
from agent.tools.base import BaseTool
from agent.tools.case import GetPaymentCaseTool
from agent.tools.decision import GetRecoveryDecisionTool
from agent.tools.action import ExecuteRecoveryActionTool
from agent.tools.action_status import GetActionStatusTool
from agent.tools.outcome import RecordRecoveryOutcomeTool
from agent.tools.summary import GetRecoverySummaryTool


class ToolRegistry:
    """
    Registry of approved recovery agent tools.
    GUARANTEE: The agent may ONLY invoke tools that are explicitly registered here.
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        self.register(GetPaymentCaseTool())
        self.register(GetRecoveryDecisionTool())
        self.register(ExecuteRecoveryActionTool())
        self.register(GetActionStatusTool())
        self.register(RecordRecoveryOutcomeTool())
        self.register(GetRecoverySummaryTool())

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        """Returns JSON schema definitions for all approved tools."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    def has_tool(self, name: str) -> bool:
        return name in self._tools


# Global default tool registry
default_tool_registry = ToolRegistry()
