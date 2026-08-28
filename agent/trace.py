"""
Agent trace encapsulation and formatting for RecoverAI Recovery Agent v0.
Provides auditable, deterministic step-by-step execution history.
"""

from typing import Any, Dict, List
from pydantic import BaseModel, ConfigDict, Field
from agent.models import AgentStep


class AgentTrace(BaseModel):
    """
    Complete chronological execution trace for an agent run.
    """
    model_config = ConfigDict(frozen=True)

    agent_run_id: str = Field(description="Unique agent run identifier")
    case_id: str = Field(description="Target payment case ID")
    steps: List[AgentStep] = Field(default_factory=list, description="Ordered sequence of executed steps")

    def to_ascii_tree(self) -> str:
        """
        Renders a clean human-readable ASCII trace tree.
        """
        lines = [f"Agent Run [{self.agent_run_id}] for Case [{self.case_id}]"]
        for idx, step in enumerate(self.steps):
            is_last = idx == len(self.steps) - 1
            prefix = "└── " if is_last else "├── "
            tool_info = f" (tool={step.tool_name})" if step.tool_name else ""
            status_info = f" [{step.status.value}]"
            lines.append(f"{prefix}{step.step_type.value}{tool_info}{status_info}")

            # Add key output details if present
            if step.output_summary:
                sub_prefix = "    " if is_last else "│   "
                for k, v in step.output_summary.items():
                    lines.append(f"{sub_prefix}└── {k} = {v}")
            if step.error_message:
                sub_prefix = "    " if is_last else "│   "
                lines.append(f"{sub_prefix}└── error: {step.error_message}")

        return "\n".join(lines)
