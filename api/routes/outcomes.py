"""
Operational outcome event endpoints for RecoverAI API.
"""

from fastapi import APIRouter, HTTPException, status
from recovery.state_machine import InvalidStateTransitionError
from api.schemas import OutcomeEventRequest, OutcomeEventResponse, ErrorResponse
from api.services.operations_service import (
    operations_service,
    DecisionNotFoundError,
    CaseNotFoundError,
    ActionNotFoundError,
    DuplicateOutcomeError,
    InvalidOutcomeAmountError,
    CaseReferenceMismatchError,
)

router = APIRouter(prefix="/recovery", tags=["Recovery Operations"])


@router.post(
    "/outcomes",
    response_model=OutcomeEventResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid outcome data or reference mismatch"},
        404: {"model": ErrorResponse, "description": "Referenced action, decision, or case not found"},
        409: {"model": ErrorResponse, "description": "Duplicate outcome or invalid state transition"},
        422: {"description": "Unprocessable Entity (Schema validation failed)"},
    },
)
async def record_recovery_outcome(request: OutcomeEventRequest):
    """
    Records an observed operational payment outcome event (e.g. webhook or gateway settlement).
    Transitions the recovery case to a terminal state (RECOVERED or NOT_RECOVERED).
    """
    try:
        outcome = operations_service.record_outcome(request)
        from api.observability import observability_registry
        observability_registry.record_outcome()
        return outcome
    except (DuplicateOutcomeError, InvalidStateTransitionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except (ActionNotFoundError, DecisionNotFoundError, CaseNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except (CaseReferenceMismatchError, InvalidOutcomeAmountError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Outcome recording error: {str(exc)}",
        )
