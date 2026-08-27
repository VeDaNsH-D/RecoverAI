"""
Model metadata and capabilities registry endpoint for RecoverAI API.
"""

from fastapi import APIRouter, HTTPException, status
from api.schemas import ModelInfoResponse
from api.services.recovery_service import recovery_service

router = APIRouter()


@router.get("/model-info", response_model=ModelInfoResponse, tags=["Model Info"])
async def get_model_info():
    """
    Returns product-safe metadata regarding the active recovery decision model.
    Excludes any ground-truth, latent variables, or training labels.
    """
    if not recovery_service.is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model artifact is currently unavailable.",
        )
    return recovery_service.get_model_info()
