"""
Operational summary and analytics endpoints for RecoverAI API.
"""

from fastapi import APIRouter
from api.schemas import RecoverySummaryResponse
from api.services.operations_service import operations_service

router = APIRouter(prefix="/recovery", tags=["Recovery Operations"])


@router.get(
    "/summary",
    response_model=RecoverySummaryResponse,
    tags=["Recovery Analytics"],
)
async def get_recovery_summary():
    """
    Returns observational operational and financial metrics across all persisted recovery cases.
    NOTE: These are observational production metrics and do not represent causal uplift.
    """
    return operations_service.get_summary()
