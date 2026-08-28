"""
Recovery decision endpoints for RecoverAI API.
"""

from fastapi import APIRouter, HTTPException, status
from api.schemas import PaymentCaseRequest, DecisionResponse, ErrorResponse
from api.services.recovery_service import recovery_service

router = APIRouter()


@router.post(
    "/decisions",
    response_model=DecisionResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid payment case request"},
        422: {"description": "Unprocessable Entity (Schema validation failed or unknown fields provided)"},
        503: {"model": ErrorResponse, "description": "Recovery decision model unavailable"},
    },
    tags=["Decisions"],
)
async def create_recovery_decision(request: PaymentCaseRequest):
    """
    Evaluates an observable failed payment incident and produces an economically optimal,
    bounded recovery action recommendation along with an auditable comparison ledger.
    """
    if not recovery_service.is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recovery decision model is unavailable or not loaded.",
        )

    try:
        decision = recovery_service.process_decision(request)
        from api.observability import observability_registry
        observability_registry.record_decision()
        return decision
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to process recovery decision: {str(exc)}",
        )
