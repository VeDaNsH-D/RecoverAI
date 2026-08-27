"""
Lifecycle state machine engine for RecoverAI payment recovery cases.
Enforces deterministic, legal state transitions and prevents invalid workflows.
"""

from typing import Dict, Set
from recovery.models import CaseState


class InvalidStateTransitionError(Exception):
    """Raised when an illegal lifecycle state transition is attempted."""
    def __init__(self, current_state: CaseState, attempted_state: CaseState, message: str = ""):
        detail = message or f"Illegal state transition from '{current_state.value}' to '{attempted_state.value}'."
        super().__init__(detail)
        self.current_state = current_state
        self.attempted_state = attempted_state


class RecoveryStateMachine:
    """
    Deterministic state machine defining and verifying allowed lifecycle transitions.
    """

    # Legal state transition graph
    LEGAL_TRANSITIONS: Dict[CaseState, Set[CaseState]] = {
        CaseState.DECIDED: {
            CaseState.ACTION_PENDING,
        },
        CaseState.ACTION_PENDING: {
            CaseState.ACTION_EXECUTED,
            CaseState.EXECUTION_FAILED,
        },
        CaseState.EXECUTION_FAILED: {
            CaseState.ACTION_PENDING,  # Retry same action permitted
        },
        CaseState.ACTION_EXECUTED: {
            CaseState.RECOVERED,
            CaseState.NOT_RECOVERED,
        },
        CaseState.RECOVERED: set(),      # Terminal state
        CaseState.NOT_RECOVERED: set(),  # Terminal state
    }

    @classmethod
    def validate_transition(cls, current_state: CaseState, next_state: CaseState) -> None:
        """
        Validates if transition from current_state to next_state is legal.
        Raises InvalidStateTransitionError if illegal.
        """
        allowed_targets = cls.LEGAL_TRANSITIONS.get(current_state, set())
        if next_state not in allowed_targets:
            raise InvalidStateTransitionError(
                current_state=current_state,
                attempted_state=next_state,
                message=(
                    f"Invalid lifecycle transition: Cannot transition case from '{current_state.value}' "
                    f"to '{next_state.value}'. Allowed next states: {[s.value for s in allowed_targets]}"
                ),
            )

    @classmethod
    def is_action_executable(cls, current_state: CaseState) -> bool:
        """Returns True if the case is in a state allowing action execution."""
        return current_state in (CaseState.DECIDED, CaseState.EXECUTION_FAILED)

    @classmethod
    def is_outcome_postable(cls, current_state: CaseState) -> bool:
        """Returns True if the case is in ACTION_EXECUTED state allowing outcome posting."""
        return current_state == CaseState.ACTION_EXECUTED

    @classmethod
    def is_terminal(cls, current_state: CaseState) -> bool:
        """Returns True if the case is in a terminal state (RECOVERED or NOT_RECOVERED)."""
        return current_state in (CaseState.RECOVERED, CaseState.NOT_RECOVERED)
