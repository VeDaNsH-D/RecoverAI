"""
Recovery Operations Service for RecoverAI API.
Coordinates state transitions, idempotency checks, action provider execution, outcome recording, and summary analytics.
"""

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, Optional
import uuid

from simulator.config import RecoveryAction
from recovery.models import (
    CaseState,
    ActionExecutionStatus,
    OutcomeStatus,
    DecisionRecord,
    ActionRecord,
    OutcomeRecord,
    RecoveryCaseRecord,
)
from recovery.state_machine import RecoveryStateMachine, InvalidStateTransitionError
from recovery.repository import RecoveryRepository, IdempotencyConflictError
from recovery.executor import ActionExecutor
from api.schemas import (
    ActionExecutionRequest,
    ActionExecutionResponse,
    OutcomeEventRequest,
    OutcomeEventResponse,
    RecoverySummaryResponse,
    ActionRecoveryMetric,
)


class DecisionNotFoundError(Exception):
    """Raised when the specified decision_id does not exist."""
    pass


class CaseNotFoundError(Exception):
    """Raised when the specified case_id does not exist."""
    pass


class ActionNotFoundError(Exception):
    """Raised when the specified action_id does not exist."""
    pass


class ActionMismatchError(Exception):
    """Raised when the requested action does not match the decision's recommended action."""
    pass


class ActionDisqualifiedError(Exception):
    """Raised when a policy-disqualified action is requested."""
    pass


class DuplicateOutcomeError(Exception):
    """Raised when an outcome is submitted for an already resolved action."""
    pass


class InvalidOutcomeAmountError(Exception):
    """Raised when recovered amount violates outcome status constraints."""
    pass


class CaseReferenceMismatchError(Exception):
    """Raised when case, action, and decision identifiers are mutually inconsistent."""
    pass


class OperationsService:
    """
    Service coordinating recovery operations, persistence, and state transitions.
    """

    def __init__(self, repository: Optional[RecoveryRepository] = None):
        self.repository = repository or RecoveryRepository(db_path="data/recovery_operations.db")
        self.executor = ActionExecutor()

    def persist_decision(
        self,
        decision_id: str,
        case_id: str,
        customer_id: str,
        amount_paise: int,
        recommended_action: RecoveryAction,
        recommended_action_recovery_probability: float,
        expected_gross_recovery_paise: int,
        action_cost_paise: int,
        expected_net_recovery_paise: int,
        decision_margin_paise: int,
        explanation: str,
        model_family: str = "calibrated_logistic_regression",
        feature_version: str = "sim_v1_canonical_24d",
        payment_method: str = "upi",
        is_subscription: bool = False,
        failure_type: str = "temporary_failure",
        retry_count: int = 0,
        created_at: Optional[str] = None,
    ) -> DecisionRecord:
        """
        Persists a newly generated decision and establishes the case in DECIDED state.
        """
        ts = created_at or datetime.now(timezone.utc).isoformat()
        record = DecisionRecord(
            decision_id=decision_id,
            case_id=case_id,
            customer_id=customer_id,
            amount_paise=amount_paise,
            recommended_action=recommended_action,
            recommended_action_recovery_probability=recommended_action_recovery_probability,
            expected_gross_recovery_paise=expected_gross_recovery_paise,
            action_cost_paise=action_cost_paise,
            expected_net_recovery_paise=expected_net_recovery_paise,
            decision_margin_paise=decision_margin_paise,
            explanation=explanation,
            model_family=model_family,
            feature_version=feature_version,
            created_at=ts,
        )
        self.repository.save_decision(
            record,
            payment_method=payment_method,
            is_subscription=is_subscription,
            failure_type=failure_type,
            retry_count=retry_count,
        )
        return record

    def execute_action(self, request: ActionExecutionRequest) -> ActionExecutionResponse:
        """
        Validates decision state and dispatches recovery action to provider.
        Enforces strict idempotency semantics.
        """
        payload_hash = hashlib.sha256(f"{request.decision_id}:{request.action.value}".encode()).hexdigest()

        # 1. Check Idempotency
        existing_action = self.repository.get_action_by_idempotency_key(request.idempotency_key)
        if existing_action is not None:
            if existing_action.payload_hash == payload_hash:
                # Idempotent replay: return original execution response
                return ActionExecutionResponse(
                    action_id=existing_action.action_id,
                    decision_id=existing_action.decision_id,
                    case_id=existing_action.case_id,
                    action=existing_action.action,
                    status=existing_action.status,
                    provider_reference=existing_action.provider_reference,
                    cost_paise=existing_action.cost_paise,
                    cost_inr=existing_action.cost_paise / 100.0,
                    error_message=existing_action.error_message,
                    executed_at=existing_action.executed_at,
                    idempotency_key=existing_action.idempotency_key,
                )
            else:
                raise IdempotencyConflictError(
                    f"Idempotency key '{request.idempotency_key}' was previously used with a different action/decision payload."
                )

        # 2. Verify Decision & Case Existence
        decision = self.repository.get_decision(request.decision_id)
        if decision is None:
            raise DecisionNotFoundError(f"Decision '{request.decision_id}' not found.")

        case = self.repository.get_case(decision.case_id)
        if case is None:
            raise CaseNotFoundError(f"Case '{decision.case_id}' not found.")

        # 3. Validate Lifecycle State
        if not RecoveryStateMachine.is_action_executable(case.current_state):
            # Attempting transition to generate standard InvalidStateTransitionError
            RecoveryStateMachine.validate_transition(case.current_state, CaseState.ACTION_PENDING)

        # 4. Validate Action Matches Decision (No merchant bypass allowed)
        if request.action != decision.recommended_action:
            raise ActionMismatchError(
                f"Requested action '{request.action.value}' does not match the decision's "
                f"recommended action '{decision.recommended_action.value}'."
            )

        # 5. Execute Action via Provider
        action_id = f"act_{uuid.uuid4().hex[:12]}"
        exec_result = self.executor.execute_action(
            case=case,
            decision=decision,
            action=request.action,
            idempotency_key=request.idempotency_key,
            force_failure=request.force_failure,
        )

        # 6. Determine Next State & Persist
        next_state = CaseState.ACTION_EXECUTED if exec_result.status == ActionExecutionStatus.EXECUTED else CaseState.EXECUTION_FAILED
        now_ts = datetime.now(timezone.utc).isoformat()

        action_record = ActionRecord(
            action_id=action_id,
            decision_id=decision.decision_id,
            case_id=case.case_id,
            action=request.action,
            idempotency_key=request.idempotency_key,
            payload_hash=payload_hash,
            status=exec_result.status,
            cost_paise=exec_result.cost_paise,
            provider_reference=exec_result.provider_reference,
            error_message=exec_result.error_message,
            executed_at=now_ts,
        )

        self.repository.record_action_execution(action_record, next_state)

        return ActionExecutionResponse(
            action_id=action_id,
            decision_id=decision.decision_id,
            case_id=case.case_id,
            action=request.action,
            status=exec_result.status,
            provider_reference=exec_result.provider_reference,
            cost_paise=exec_result.cost_paise,
            cost_inr=exec_result.cost_paise / 100.0,
            error_message=exec_result.error_message,
            executed_at=now_ts,
            idempotency_key=request.idempotency_key,
        )

    def get_action(self, action_id: str) -> ActionExecutionResponse:
        """Retrieves action execution details by action ID."""
        action = self.repository.get_action(action_id)
        if action is None:
            raise ActionNotFoundError(f"Action '{action_id}' not found.")

        return ActionExecutionResponse(
            action_id=action.action_id,
            decision_id=action.decision_id,
            case_id=action.case_id,
            action=action.action,
            status=action.status,
            provider_reference=action.provider_reference,
            cost_paise=action.cost_paise,
            cost_inr=action.cost_paise / 100.0,
            error_message=action.error_message,
            executed_at=action.executed_at,
            idempotency_key=action.idempotency_key,
        )

    def record_outcome(self, request: OutcomeEventRequest) -> OutcomeEventResponse:
        """
        Validates and records an observed operational outcome event.
        """
        # 1. Verify existence of action, decision, case
        action = self.repository.get_action(request.action_id)
        if action is None:
            raise ActionNotFoundError(f"Action '{request.action_id}' not found.")

        decision = self.repository.get_decision(request.decision_id)
        if decision is None:
            raise DecisionNotFoundError(f"Decision '{request.decision_id}' not found.")

        case = self.repository.get_case(request.case_id)
        if case is None:
            raise CaseNotFoundError(f"Case '{request.case_id}' not found.")

        # 2. Check Reference Consistency
        if action.case_id != request.case_id or action.decision_id != request.decision_id:
            raise CaseReferenceMismatchError(
                f"Action '{request.action_id}' does not match case '{request.case_id}' or decision '{request.decision_id}'."
            )

        # 3. Check for Duplicate Outcome
        existing_outcome = self.repository.get_outcome_by_action_id(request.action_id)
        if existing_outcome is not None:
            raise DuplicateOutcomeError(f"Outcome has already been recorded for action '{request.action_id}'.")

        # 4. Check State Machine Validity (Must be in ACTION_EXECUTED)
        if not RecoveryStateMachine.is_outcome_postable(case.current_state):
            target_state = CaseState.RECOVERED if request.outcome_status == OutcomeStatus.RECOVERED else CaseState.NOT_RECOVERED
            RecoveryStateMachine.validate_transition(case.current_state, target_state)

        # 5. Validate Amount Semantics
        if request.outcome_status == OutcomeStatus.RECOVERED:
            if request.recovered_amount_paise <= 0:
                raise InvalidOutcomeAmountError(
                    f"Recovered outcome must have a positive recovered amount (got {request.recovered_amount_paise} paise)."
                )
        elif request.outcome_status == OutcomeStatus.NOT_RECOVERED:
            if request.recovered_amount_paise != 0:
                raise InvalidOutcomeAmountError(
                    f"Not-recovered outcome cannot have non-zero recovered amount (got {request.recovered_amount_paise} paise)."
                )

        # 6. Record Outcome & Transition Case to Terminal State
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        now_ts = datetime.now(timezone.utc).isoformat()
        evt_ts = request.event_timestamp or now_ts
        next_state = CaseState.RECOVERED if request.outcome_status == OutcomeStatus.RECOVERED else CaseState.NOT_RECOVERED

        outcome_record = OutcomeRecord(
            event_id=event_id,
            action_id=action.action_id,
            case_id=case.case_id,
            decision_id=decision.decision_id,
            outcome_status=request.outcome_status,
            recovered_amount_paise=request.recovered_amount_paise,
            provider_reference=request.provider_reference or action.provider_reference,
            metadata=request.metadata,
            event_timestamp=evt_ts,
            created_at=now_ts,
        )

        self.repository.record_outcome(outcome_record, next_state)

        return OutcomeEventResponse(
            event_id=event_id,
            case_id=case.case_id,
            action_id=action.action_id,
            decision_id=decision.decision_id,
            outcome_status=request.outcome_status,
            recovered_amount_paise=request.recovered_amount_paise,
            recovered_amount_inr=request.recovered_amount_paise / 100.0,
            event_timestamp=evt_ts,
            created_at=now_ts,
        )

    def get_summary(self) -> RecoverySummaryResponse:
        """Computes merchant operational summary analytics."""
        raw = self.repository.get_summary_metrics()
        now_ts = datetime.now(timezone.utc).isoformat()

        rec_by_action = {
            act: ActionRecoveryMetric(**data)
            for act, data in raw["recovery_by_action"].items()
        }

        return RecoverySummaryResponse(
            total_cases=raw["total_cases"],
            decisions_made=raw["decisions_made"],
            actions_executed=raw["actions_executed"],
            execution_failures=raw["execution_failures"],
            recovered_cases=raw["recovered_cases"],
            not_recovered_cases=raw["not_recovered_cases"],
            recovery_rate=raw["recovery_rate"],
            gross_recovered_paise=raw["gross_recovered_paise"],
            gross_recovered_inr=raw["gross_recovered_inr"],
            total_action_cost_paise=raw["action_cost_paise"],
            total_action_cost_inr=raw["action_cost_inr"],
            net_recovered_paise=raw["net_recovered_paise"],
            net_recovered_inr=raw["net_recovered_inr"],
            action_distribution=raw["action_distribution"],
            recovery_by_action=rec_by_action,
            execution_failures_by_action=raw["execution_failures_by_action"],
            timestamp=now_ts,
        )


# Global operations service instance
operations_service = OperationsService()
