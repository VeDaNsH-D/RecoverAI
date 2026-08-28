"""
Domain models for RecoverAI Recovery Agent v0.
Defines AgentRun, AgentStep, AgentContext, and execution lifecycle enums.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class AgentModel(ABC):
    """
    Abstract driver interface for deciding the next tool invocation.
    Allows Deterministic and LLM drivers to drive tool selection without altering the runtime or tools.
    """

    @abstractmethod
    def decide_next_tool(
        self,
        context: "AgentContext",
        available_tools: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates current agent context and returns the next structured tool call or None when complete.
        Format: {"tool": "tool_name", "arguments": {...}, "metadata": {...}}
        """
        pass


class FailureCategory(str, Enum):
    """
    Explicit taxonomy for recovery agent failure classification.
    """
    NONE = "none"
    MODEL_ERROR = "MODEL_ERROR"                  # LLM provider error, timeout, malformed output
    INVALID_TOOL_CALL = "INVALID_TOOL_CALL"      # Unknown tool, malformed JSON arguments
    POLICY_VIOLATION = "POLICY_VIOLATION"        # Action substitution, lifecycle violation, bypass attempt
    EXECUTION_FAILURE = "EXECUTION_FAILURE"      # Provider/gateway technical execution error
    WORKFLOW_FAILURE = "WORKFLOW_FAILURE"        # Step limit exceeded, premature stop


class AgentRunStatus(str, Enum):
    STARTED = "started"
    DECISION_OBTAINED = "decision_obtained"
    ACTION_EXECUTED = "action_executed"
    ACTION_FAILED = "action_failed"
    COMPLETED = "completed"
    FAILED = "failed"


class StepType(str, Enum):
    CASE_RETRIEVED = "CASE_RETRIEVED"
    DECISION_REQUESTED = "DECISION_REQUESTED"
    DECISION_OBTAINED = "DECISION_OBTAINED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    ACTION_REQUESTED = "ACTION_REQUESTED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    ACTION_FAILED = "ACTION_FAILED"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"
    COMPLETED = "COMPLETED"


class StepStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentStep(BaseModel):
    """
    Individual auditable step recorded during an agent execution run.
    """
    model_config = ConfigDict(frozen=True)

    step_id: str = Field(description="Unique identifier for the step")
    agent_run_id: str = Field(description="Associated agent run ID")
    step_index: int = Field(description="Sequential step index (0-indexed)")
    step_type: StepType = Field(description="Lifecycle step classification")
    tool_name: Optional[str] = Field(default=None, description="Name of the tool invoked if applicable")
    input_summary: Dict[str, Any] = Field(default_factory=dict, description="Safe input parameters summary")
    output_summary: Dict[str, Any] = Field(default_factory=dict, description="Safe output result summary")
    status: StepStatus = Field(description="Execution status of the step")
    failure_category: Optional[str] = Field(default=None, description="Explicit failure classification if failed")
    error_message: Optional[str] = Field(default=None, description="Error detail if step failed")
    llm_prompt_tokens: Optional[int] = Field(default=None, description="Prompt token count if LLM-driven")
    llm_completion_tokens: Optional[int] = Field(default=None, description="Completion token count if LLM-driven")
    llm_latency_ms: Optional[float] = Field(default=None, description="LLM call latency in ms if applicable")
    started_at: str = Field(description="ISO 8601 timestamp when step began")
    completed_at: Optional[str] = Field(default=None, description="ISO 8601 timestamp when step ended")


class AgentContext(BaseModel):
    """
    Working memory of the Recovery Agent during workflow orchestration.
    Contains ONLY observable context and persisted references.
    GUARANTEE: Zero access to latent simulator variables or ground truth.
    """
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(description="Payment case identifier")
    customer_id: Optional[str] = Field(default=None, description="Customer identifier")
    amount_paise: Optional[int] = Field(default=None, description="Amount at risk in integer paise")
    currency: str = Field(default="INR", description="Transaction currency")
    payment_method: Optional[str] = Field(default=None, description="Payment method")
    is_subscription: Optional[bool] = Field(default=None, description="Subscription indicator")
    failure_type: Optional[str] = Field(default=None, description="Observable failure type")
    retry_count: int = Field(default=0, description="Prior retry attempts count")
    hours_since_failure: float = Field(default=0.0, description="Hours elapsed since failure")

    # Authoritative Decision State (Derived strictly from RecoveryDecisionEngine)
    decision_id: Optional[str] = Field(default=None, description="Persisted decision record ID")
    recommended_action: Optional[str] = Field(default=None, description="Recommended action name")
    recovery_probability: Optional[float] = Field(default=None, description="P(Y=1 | X, recommended_action)")
    expected_gross_paise: Optional[int] = Field(default=None, description="Expected gross recovery in paise")
    action_cost_paise: Optional[int] = Field(default=None, description="Action cost in paise")
    expected_net_paise: Optional[int] = Field(default=None, description="Expected net recovery in paise")
    decision_margin_paise: Optional[int] = Field(default=None, description="Decision margin over alternative")
    explanation: Optional[str] = Field(default=None, description="Merchant rationale")

    # Action Execution State
    action_id: Optional[str] = Field(default=None, description="Persisted action execution ID")
    execution_status: Optional[str] = Field(default=None, description="Action execution status (EXECUTED, FAILED)")
    provider_reference: Optional[str] = Field(default=None, description="External provider transaction reference")
    current_operational_state: Optional[str] = Field(default=None, description="Operational case state")

    # Outcome State
    outcome_status: Optional[str] = Field(default=None, description="Settled outcome (recovered, not_recovered)")
    recovered_amount_paise: Optional[int] = Field(default=None, description="Actual recovered amount in paise")


class AgentRun(BaseModel):
    """
    Complete state record of an autonomous agent recovery run.
    """
    model_config = ConfigDict(frozen=True)

    agent_run_id: str = Field(description="Unique agent run identifier")
    case_id: str = Field(description="Target payment case ID")
    decision_id: Optional[str] = Field(default=None, description="Associated decision ID")
    idempotency_key: Optional[str] = Field(default=None, description="Unique idempotency key")
    status: AgentRunStatus = Field(description="Current agent run status")
    recommended_action: Optional[str] = Field(default=None, description="Action recommended by decision engine")
    final_action: Optional[str] = Field(default=None, description="Action executed by agent")
    final_operational_state: Optional[str] = Field(default=None, description="Final operational case state")
    driver_type: str = Field(default="deterministic", description="Agent driver strategy (deterministic, llm)")
    failure_category: Optional[str] = Field(default=None, description="Explicit failure category if failed")
    error_message: Optional[str] = Field(default=None, description="Error detail if run failed")
    llm_provider: Optional[str] = Field(default=None, description="LLM provider name if applicable")
    llm_model: Optional[str] = Field(default=None, description="LLM model name if applicable")
    prompt_version: Optional[str] = Field(default=None, description="System prompt version if applicable")
    total_tokens: int = Field(default=0, description="Total tokens consumed during run")
    llm_latency_ms: float = Field(default=0.0, description="Cumulative LLM latency in ms")
    started_at: str = Field(description="ISO 8601 timestamp when run started")
    completed_at: Optional[str] = Field(default=None, description="ISO 8601 timestamp when run ended")
