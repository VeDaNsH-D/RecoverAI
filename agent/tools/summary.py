"""
Recovery operational summary tool for RecoverAI Agent.
"""

from typing import Any, Dict
from agent.tools.base import BaseTool
from agent.models import AgentContext
from api.services.operations_service import operations_service


class GetRecoverySummaryTool(BaseTool):
    """
    Tool to inspect high-level recovery ledger statistics and operational rates.
    """

    @property
    def name(self) -> str:
        return "get_recovery_summary"

    @property
    def description(self) -> str:
        return "Returns high-level aggregate operational KPIs, recovery rates, and integer-paise financial ledgers."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    def execute(self, context: AgentContext, **kwargs: Any) -> Dict[str, Any]:
        summary_resp = operations_service.get_summary()
        return summary_resp.model_dump()
