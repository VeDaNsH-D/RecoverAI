"""
Health and readiness endpoints for RecoverAI API.
"""

from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from api.schemas import HealthResponse, ReadinessResponse
from api.services.recovery_service import recovery_service
from api.services.operations_service import operations_service

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def get_health():
    """
    Process liveness probe.
    Returns whether the application process is running.
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


@router.get("/ready", response_model=ReadinessResponse, tags=["Health"])
async def get_readiness():
    """
    Dependency readiness probe.
    Verifies critical runtime dependencies: champion model artifact and database connectivity.
    """
    model_ok = recovery_service.is_ready
    db_ok = operations_service.repository.is_ready()

    is_ready = model_ok and db_ok
    payload = ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        model_status="ready" if model_ok else "unavailable",
        database_status="connected" if db_ok else "disconnected",
        model_family=recovery_service.model_family if model_ok else None,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    if not is_ready:
        return JSONResponse(status_code=503, content=payload.model_dump())
    return payload
