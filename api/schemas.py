"""
Merchant-facing Pydantic schemas and API contracts for RecoverAI.
SECURITY GUARANTEE: Ingests ONLY observable payment features with closed schemas (extra='forbid').
Zero ground-truth or latent variables can enter the API contract.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import FailureType, PaymentMethod, RecoveryAction
from simulator.schemas.case import PaymentCase
from recovery.models import ActionExecutionStatus, OutcomeStatus


class PaymentCaseRequest(BaseModel):
    """
    Merchant request schema representing an observable payment failure incident.
    GUARANTEE: Closed schema (extra='forbid') structurally rejecting any unrecognized or forbidden fields.
    """
    model_config = ConfigDict(extra="forbid")

    # Identifiers & Metadata (Bookkeeping only, never passed to ML feature matrix)
    case_id: Optional[str] = Field(default=None, description="Merchant case or transaction identifier")
    customer_id: Optional[str] = Field(default=None, description="Associated customer reference identifier")
    merchant_id: Optional[str] = Field(default="merch_recoverai_prod", description="Merchant account ID")
    created_at: Optional[str] = Field(default=None, description="ISO 8601 incident timestamp")

    # Financial Data (Strict Integer Paise)
    amount_paise: int = Field(ge=0, description="Transaction value in integer paise (1 INR = 100 paise)")
    currency: str = Field(default="INR", description="Currency code (e.g. INR)")

    # Observable Payment Context
    payment_method: PaymentMethod = Field(description="Payment method used (upi, card, netbanking, mandate)")
    is_subscription: bool = Field(default=False, description="Whether transaction is a recurring subscription")

    # Historical Customer Context (Observable aggregates)
    customer_historical_success_rate: float = Field(ge=0.0, le=1.0, description="Customer historical success rate [0.0, 1.0]")
    customer_total_transactions: int = Field(ge=0, description="Customer lifetime transaction count")
    customer_total_failures: int = Field(ge=0, description="Customer lifetime failure count")
    customer_avg_amount_paise: int = Field(ge=0, description="Customer average transaction amount in paise")
    customer_tenure_months: int = Field(ge=0, description="Customer tenure in months")

    # Incident Diagnostics
    failure_type: FailureType = Field(description="Diagnosed failure reason (temporary_failure, insufficient_funds, etc.)")
    retry_count: int = Field(default=0, ge=0, description="Number of recovery retries already attempted")
    hours_since_failure: float = Field(default=0.0, ge=0.0, description="Elapsed time in hours since failure occurred")

    def to_payment_case(self) -> PaymentCase:
        """
        Converts the API request into the authoritative domain PaymentCase.
        Explicitly separates metadata from ML observable inputs.
        """
        generated_case_id = self.case_id or f"case_{uuid.uuid4().hex[:8]}"
        generated_cust_id = self.customer_id or f"cust_{uuid.uuid4().hex[:8]}"
        ts = self.created_at or datetime.now(timezone.utc).isoformat()

        return PaymentCase(
            case_id=generated_case_id,
            customer_id=generated_cust_id,
            merchant_id=self.merchant_id or "merch_recoverai_prod",
            amount_paise=self.amount_paise,
            currency=self.currency,
            payment_method=self.payment_method,
            is_subscription=self.is_subscription,
            customer_historical_success_rate=self.customer_historical_success_rate,
            customer_total_transactions=self.customer_total_transactions,
            customer_total_failures=self.customer_total_failures,
            customer_avg_amount_paise=self.customer_avg_amount_paise,
            customer_tenure_months=self.customer_tenure_months,
            failure_type=self.failure_type,
            retry_count=self.retry_count,
            hours_since_failure=self.hours_since_failure,
            created_at=ts,
        )


class CandidateActionResponse(BaseModel):
    """Detailed economic evaluation and safety audit for a single candidate action."""
    model_config = ConfigDict(frozen=True)

    action: RecoveryAction = Field(description="Candidate recovery action")
    recovery_probability: float = Field(ge=0.0, le=1.0, description="Estimated recovery probability P(Y(a)=1 | X)")
    expected_gross_recovery_paise: int = Field(ge=0, description="floor(recovery_probability * amount_paise)")
    expected_gross_recovery_inr: float = Field(ge=0.0, description="Expected gross recovery in INR")
    action_cost_paise: int = Field(ge=0, description="Friction / operational cost in paise")
    action_cost_inr: float = Field(ge=0.0, description="Friction cost in INR")
    expected_net_recovery_paise: int = Field(description="Gross - Cost in paise")
    expected_net_recovery_inr: float = Field(description="Gross - Cost in INR")
    allowed: bool = Field(description="Whether action satisfies safety policy constraints")
    disqualification_reason: Optional[str] = Field(default=None, description="Policy disqualification rationale if blocked")


class SafetyStatusResponse(BaseModel):
    """Safety guardrail audit status for a recovery decision."""
    model_config = ConfigDict(frozen=True)

    guardrails_applied: List[str] = Field(description="List of active policy rules evaluated")
    retry_disqualified: bool = Field(description="Whether retry was blocked by retry exhaustion guardrail")
    escalate_disqualified: bool = Field(description="Whether escalation was blocked by micro-ticket guardrail")


class DecisionResponse(BaseModel):
    """Merchant-facing recovery decision response."""
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(description="Unique identifier for the decision record")
    case_id: Optional[str] = Field(description="Associated payment case ID")
    recommended_action: RecoveryAction = Field(description="Economically optimal selected recovery action")
    recommended_action_recovery_probability: float = Field(
        ge=0.0, le=1.0, description="Estimated recovery probability for the recommended action P(Y=1 | X, recommended_action)"
    )
    expected_gross_recovery_paise: int = Field(description="Expected gross yield in integer paise")
    expected_gross_recovery_inr: float = Field(description="Expected gross yield in INR")
    action_cost_paise: int = Field(description="Operational friction cost in integer paise")
    action_cost_inr: float = Field(description="Operational friction cost in INR")
    expected_net_recovery_paise: int = Field(description="Expected net recovery value in integer paise")
    expected_net_recovery_inr: float = Field(description="Expected net recovery value in INR")
    decision_margin_paise: int = Field(ge=0, description="Expected net gain over next-best allowed action in paise")
    decision_margin_inr: float = Field(ge=0.0, description="Expected net gain over next-best allowed action in INR")
    explanation: str = Field(description="Merchant-friendly deterministic decision rationale")
    safety_status: SafetyStatusResponse = Field(description="Safety guardrails audit report")
    candidate_actions: List[CandidateActionResponse] = Field(description="Full audit ledger of all candidate actions evaluated")
    timestamp: str = Field(description="ISO 8601 decision timestamp")


class HealthResponse(BaseModel):
    """Service health and model readiness response."""
    model_config = ConfigDict(frozen=True)

    status: str = Field(description="Overall service status (healthy / degraded)")
    service: str = Field(default="recoverai-decision-engine")
    version: str = Field(default="0.1.0")
    model_status: str = Field(description="Model load status (ready / model_unavailable)")
    model_family: Optional[str] = Field(default=None, description="Active champion model family")
    timestamp: str = Field(description="Current ISO 8601 timestamp")


class ModelInfoResponse(BaseModel):
    """Product-safe model metadata and capability registry."""
    model_config = ConfigDict(frozen=True)

    model_family: str = Field(description="Champion model architecture family")
    feature_version: str = Field(description="Observable feature schema specification version")
    simulator_version: str = Field(description="Underlying simulation benchmark version")
    supported_actions: List[RecoveryAction] = Field(description="Supported bounded recovery action space")
    feature_count: int = Field(description="Number of observable input features utilized")
    active_safety_guardrails: List[str] = Field(description="Active policy guardrails enforced during decisioning")
    training_status: str = Field(description="Model lifecycle status (e.g. trained_and_frozen)")
    disclaimer: str = Field(description="Scientific boundary disclaimer regarding observable-only inference")


class ActionExecutionRequest(BaseModel):
    """
    Request to execute an action selected by RecoverAI Decision Engine.
    GUARANTEE: Closed schema (extra='forbid') rejecting any unauthorized extra fields.
    """
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(description="Reference ID of the preceding RecoverAI decision")
    action: RecoveryAction = Field(description="Recovery action to execute (must match recommended action)")
    idempotency_key: str = Field(min_length=8, description="Merchant unique idempotency key for safe retries")
    merchant_reference: Optional[str] = Field(default=None, description="Optional merchant system reference")
    force_failure: bool = Field(default=False, description="Flag for testing mock provider technical failures")


class ActionExecutionResponse(BaseModel):
    """Response confirming action execution dispatch."""
    model_config = ConfigDict(frozen=True)

    action_id: str = Field(description="Unique identifier for the action execution record")
    decision_id: str = Field(description="Associated decision ID")
    case_id: str = Field(description="Associated payment case ID")
    action: RecoveryAction = Field(description="Action executed")
    status: ActionExecutionStatus = Field(description="Execution status (EXECUTED or FAILED)")
    provider_reference: str = Field(description="Reference ID returned by downstream provider/mock")
    cost_paise: int = Field(ge=0, description="Actual action operational cost in integer paise")
    cost_inr: float = Field(ge=0.0, description="Actual action cost in INR")
    error_message: Optional[str] = Field(default=None, description="Error detail if execution failed")
    executed_at: str = Field(description="ISO 8601 execution timestamp")
    idempotency_key: str = Field(description="Idempotency key associated with this execution")


class OutcomeEventRequest(BaseModel):
    """
    Observed operational outcome event reporting payment resolution.
    GUARANTEE: Closed schema (extra='forbid').
    """
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(description="Associated payment case ID")
    action_id: str = Field(description="Associated action execution ID")
    decision_id: str = Field(description="Associated decision ID")
    outcome_status: OutcomeStatus = Field(description="Operational outcome status ('recovered' or 'not_recovered')")
    recovered_amount_paise: int = Field(ge=0, description="Amount recovered in integer paise (0 if not recovered)")
    provider_reference: Optional[str] = Field(default=None, description="External provider transaction reference")
    resolution_source: Optional[str] = Field(default=None, description="Attribution: recoverai_intervention or provider_auto_retry")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary observational event metadata")
    event_timestamp: Optional[str] = Field(default=None, description="ISO 8601 timestamp when outcome occurred")


class OutcomeEventResponse(BaseModel):
    """Confirmation of recorded operational outcome event."""
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(description="Unique identifier for the outcome event record")
    case_id: str = Field(description="Associated payment case ID")
    action_id: str = Field(description="Associated action ID")
    decision_id: str = Field(description="Associated decision ID")
    outcome_status: OutcomeStatus = Field(description="Operational outcome status ('recovered' or 'not_recovered')")
    recovered_amount_paise: int = Field(description="Recovered amount in integer paise")
    recovered_amount_inr: float = Field(description="Recovered amount in INR")
    resolution_source: Optional[str] = Field(default=None, description="Attribution: recoverai_intervention or provider_auto_retry")
    event_timestamp: str = Field(description="ISO 8601 timestamp of outcome event")
    created_at: str = Field(description="ISO 8601 recording timestamp")


class SubscriptionResponse(BaseModel):
    """Subscription detail response model."""
    model_config = ConfigDict(frozen=True)

    subscription_id: str
    customer_id: str
    plan_id: Optional[str] = None
    status: str
    current_cycle: int
    total_cycles: Optional[int] = None
    amount_due_paise: int
    amount_due_inr: float
    currency: str = "INR"
    charge_attempt_count: int = 0
    next_charge_at: Optional[str] = None
    last_case_id: Optional[str] = None
    is_recoverable: bool = True
    created_at: str
    updated_at: str


class SubscriptionSyncRequest(BaseModel):
    """Request model for active subscription reconciliation."""
    model_config = ConfigDict(extra="forbid")

    subscription_id: str = Field(..., description="Target Razorpay subscription ID (e.g. sub_xxx)")


class ActionRecoveryMetric(BaseModel):
    """Operational summary metrics for a specific recovery action."""
    model_config = ConfigDict(frozen=True)

    action: str
    executed_count: int
    recovered_count: int
    recovery_rate: float
    gross_recovered_paise: int
    gross_recovered_inr: float
    action_cost_paise: int
    action_cost_inr: float
    net_recovered_paise: int
    net_recovered_inr: float


class RecoverySummaryResponse(BaseModel):
    """Merchant operational summary analytics response."""
    model_config = ConfigDict(frozen=True)

    total_cases: int
    decisions_made: int
    actions_executed: int
    execution_failures: int
    recovered_cases: int
    not_recovered_cases: int
    recovery_rate: float
    gross_recovered_paise: int
    gross_recovered_inr: float
    total_action_cost_paise: int
    total_action_cost_inr: float
    net_recovered_paise: int
    net_recovered_inr: float
    action_distribution: Dict[str, int]
    recovery_by_action: Dict[str, ActionRecoveryMetric]
    execution_failures_by_action: Dict[str, int]
    timestamp: str


class ReadinessResponse(BaseModel):
    """Deep readiness probe verifying critical runtime dependencies."""
    model_config = ConfigDict(frozen=True)

    status: str = Field(description="Readiness status (ready or not_ready)")
    model_status: str = Field(description="Champion recovery model status (ready or unavailable)")
    database_status: str = Field(description="Database connectivity status (connected or disconnected)")
    model_family: Optional[str] = Field(default=None, description="Active champion model family")
    timestamp: str = Field(description="ISO 8601 readiness check timestamp")


class ObservabilityMetricsResponse(BaseModel):
    """Operational telemetry and traffic statistics."""
    model_config = ConfigDict(frozen=True)

    uptime_seconds: float = Field(description="Process uptime in seconds")
    requests_total: int = Field(description="Total HTTP requests processed")
    responses_2xx: int = Field(description="Total 2xx success responses")
    responses_4xx: int = Field(description="Total 4xx client error responses")
    responses_5xx: int = Field(description="Total 5xx server error responses")
    avg_latency_ms: float = Field(description="Average request processing duration in ms")
    decisions_generated: int = Field(description="Total recovery decisions generated")
    actions_dispatched: int = Field(description="Total action provider executions dispatched")
    execution_failures: int = Field(description="Total technical execution failures")
    outcomes_recorded: int = Field(description="Total observed outcomes settled")
    timestamp: str = Field(description="ISO 8601 metrics collection timestamp")


class ErrorDetail(BaseModel):
    """Structured error object."""
    model_config = ConfigDict(frozen=True)

    code: str = Field(description="Machine-readable error classification code")
    message: str = Field(description="Human-readable error description")
    request_id: Optional[str] = Field(default=None, description="Correlated request ID for troubleshooting")


class ErrorEnvelope(BaseModel):
    """Standardized top-level API error response format."""
    model_config = ConfigDict(frozen=True)

    error: ErrorDetail = Field(description="Structured error details")
    timestamp: str = Field(description="ISO 8601 error timestamp")


class ErrorResponse(BaseModel):
    """Backward-compatible error response format."""
    model_config = ConfigDict(frozen=True)

    error: str = Field(description="Error category code")
    detail: str = Field(description="Human-readable explanation of error")
    timestamp: str = Field(description="ISO 8601 error timestamp")
    request_id: Optional[str] = Field(default=None, description="Request correlation ID")
