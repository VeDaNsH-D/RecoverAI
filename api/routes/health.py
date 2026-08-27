"""
Health and readiness endpoints for RecoverAI API.
"""

from datetime import datetime, timezone
from fastapi import APIRouter
from api.schemas import HealthResponse
from api.services.recovery_service import recovery_service

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def get_health():
    """
    Returns service health status and model availability.
    """
    is_ready = recovery_service.is_ready
    status = "healthy" if is_ready else "degraded"
    model_status = "ready" if is_ready else "model_unavailable"

    return HealthResponse(
        status=status,
        service="recoverai-decision-engine",
        version="0.1.0",
        model_status=model_status,
        model_family=recovery_service.model_family if is_ready else None,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
