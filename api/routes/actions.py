"""
Action execution endpoints for RecoverAI API.
"""

from fastapi import APIRouter, HTTPException, status
from recovery.state_machine import InvalidStateTransitionError
from recovery.repository import IdempotencyConflictError
from api.schemas import ActionExecutionRequest, ActionExecutionResponse, ErrorResponse
from api.services.operations_service import (
    operations_service,
    DecisionNotFoundError,
    CaseNotFoundError,
    ActionMismatchError,
    ActionDisqualifiedError,
    ActionNotFoundError,
)

router = APIRouter(prefix="/recovery", tags=["Recovery Operations"])


@router.post(
    "/actions",
    response_model=ActionExecutionResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Action validation failed"},
        404: {"model": ErrorResponse, "description": "Referenced decision or case not found"},
        409: {"model": ErrorResponse, "description": "Idempotency conflict or invalid state transition"},
        422: {"description": "Unprocessable Entity (Schema validation failed)"},
    },
)
async def execute_recovery_action(request: ActionExecutionRequest):
    """
    Executes the recommended recovery action for a decided payment case.
    Guarantees strict idempotency and state machine enforcement.
    """
    try:
        return operations_service.execute_action(request)
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except InvalidStateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except (DecisionNotFoundError, CaseNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except (ActionMismatchError, ActionDisqualifiedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Action execution error: {str(exc)}",
        )


@router.get(
    "/actions/{action_id}",
    response_model=ActionExecutionResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse, "description": "Action record not found"},
    },
)
async def get_recovery_action(action_id: str):
    """
    Retrieves the execution status and provider reference of an action execution record.
    """
    try:
        return operations_service.get_action(action_id)
    except ActionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
