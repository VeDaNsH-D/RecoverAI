"""
Agent execution result schema for RecoverAI Recovery Agent v0.
Provides comprehensive audit information, financial ledgers, and operational state.
"""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from agent.trace import AgentTrace


class AgentResult(BaseModel):
    """
    Structured outcome of an autonomous agent recovery run.
    Contains decision audit, execution status, exact financial accounting, and trace history.
    """
    model_config = ConfigDict(frozen=True)

    agent_run_id: str = Field(description="Unique agent execution identifier")
    case_id: str = Field(description="Target payment case ID")
    decision_id: Optional[str] = Field(default=None, description="Persisted decision record ID")
    action_id: Optional[str] = Field(default=None, description="Persisted action execution ID")
    recommended_action: Optional[str] = Field(default=None, description="Action recommended by decision engine")
    executed_action: Optional[str] = Field(default=None, description="Action dispatched by agent")
    execution_status: Optional[str] = Field(default=None, description="Action execution status (EXECUTED, FAILED, SKIPPED)")
    final_operational_state: Optional[str] = Field(default=None, description="Final state in recovery state machine")

    # Financial & Probabilistic Estimates (Integer Paise)
    recovery_probability: Optional[float] = Field(default=None, description="Calibrated recovery probability")
    expected_gross_paise: Optional[int] = Field(default=None, description="Expected gross recovery in paise")
    expected_gross_inr: Optional[float] = Field(default=None, description="Expected gross recovery in INR")
    action_cost_paise: Optional[int] = Field(default=None, description="Action cost in paise")
    action_cost_inr: Optional[float] = Field(default=None, description="Action cost in INR")
    expected_net_paise: Optional[int] = Field(default=None, description="Expected net recovery in paise")
    expected_net_inr: Optional[float] = Field(default=None, description="Expected net recovery in INR")
    decision_margin_paise: Optional[int] = Field(default=None, description="Decision margin in paise")

    # Actual Observed Outcome (if settled during run)
    outcome_status: Optional[str] = Field(default=None, description="Operational outcome status (recovered, not_recovered)")
    recovered_amount_paise: Optional[int] = Field(default=None, description="Actual amount recovered in paise")
    recovered_amount_inr: Optional[float] = Field(default=None, description="Actual amount recovered in INR")
    provider_reference: Optional[str] = Field(default=None, description="Provider transaction reference")
    explanation: Optional[str] = Field(default=None, description="Merchant rationale")

    # Lifecycle & Trace
    status: str = Field(description="Agent run status (completed, failed)")
    driver_type: str = Field(default="deterministic", description="Agent driver strategy (deterministic, llm)")
    failure_category: Optional[str] = Field(default=None, description="Explicit failure category if failed")
    error_message: Optional[str] = Field(default=None, description="Error detail if run failed")
    total_tokens: int = Field(default=0, description="Total tokens consumed during run")
    llm_latency_ms: float = Field(default=0.0, description="Cumulative LLM latency in ms")
    started_at: str = Field(description="ISO 8601 run start timestamp")
    completed_at: Optional[str] = Field(default=None, description="ISO 8601 run completion timestamp")
    trace: AgentTrace = Field(description="Complete step-by-step trace of the execution")
