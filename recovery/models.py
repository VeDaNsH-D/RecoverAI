"""
Domain models and lifecycle enumerations for RecoverAI Recovery Operations.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import RecoveryAction


class CaseState(str, Enum):
    """
    Lifecycle states for a recovery case.
    """
    DECIDED = "DECIDED"
    ACTION_PENDING = "ACTION_PENDING"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    RECOVERED = "RECOVERED"
    NOT_RECOVERED = "NOT_RECOVERED"


class ActionExecutionStatus(str, Enum):
    """Status of an action provider execution attempt."""
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class OutcomeStatus(str, Enum):
    """Observed operational outcome status."""
    RECOVERED = "recovered"
    NOT_RECOVERED = "not_recovered"


class DecisionRecord(BaseModel):
    """Immutable domain record of a historical RecoverAI recovery decision."""
    model_config = ConfigDict(frozen=True)

    decision_id: str
    case_id: str
    customer_id: str
    amount_paise: int
    recommended_action: RecoveryAction
    recommended_action_recovery_probability: float
    expected_gross_recovery_paise: int
    action_cost_paise: int
    expected_net_recovery_paise: int
    decision_margin_paise: int
    explanation: str
    model_family: str
    feature_version: str
    created_at: str


class ActionRecord(BaseModel):
    """Record of an action execution dispatched to a provider."""
    model_config = ConfigDict(frozen=True)

    action_id: str
    decision_id: str
    case_id: str
    action: RecoveryAction
    idempotency_key: str
    payload_hash: str
    status: ActionExecutionStatus
    cost_paise: int
    provider_reference: str
    error_message: Optional[str] = None
    executed_at: str


class OutcomeRecord(BaseModel):
    """Record of an observed operational payment outcome event."""
    model_config = ConfigDict(frozen=True)

    event_id: str
    action_id: str
    case_id: str
    decision_id: str
    outcome_status: OutcomeStatus
    recovered_amount_paise: int
    provider_reference: Optional[str] = None
    resolution_source: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    event_timestamp: str
    created_at: str


class RecoveryCaseRecord(BaseModel):
    """Stateful record tracking the complete recovery lifecycle of a failed payment case."""
    model_config = ConfigDict(frozen=True)

    case_id: str
    customer_id: str
    amount_paise: int
    current_state: CaseState
    decision_id: str
    recommended_action: RecoveryAction
    payment_method: Optional[str] = None
    is_subscription: bool = False
    failure_type: Optional[str] = None
    retry_count: int = 0
    subscription_id: Optional[str] = None
    billing_cycle_id: Optional[str] = None
    recovery_source: Optional[str] = "one_off"
    resolution_source: Optional[str] = None
    last_action_id: Optional[str] = None
    last_action_status: Optional[ActionExecutionStatus] = None
    outcome_status: Optional[OutcomeStatus] = None
    recovered_amount_paise: Optional[int] = None
    created_at: str
    updated_at: str
