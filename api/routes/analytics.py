"""
Merchant-facing Analytics API endpoints for RecoverAI.
Provides observational metrics over cases, actions, outcomes, and costs.
NON-NEGOTIABLE: All metrics are descriptive and observational. Zero causal claims.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status

from simulator.config import FailureType, RecoveryAction
from analytics.models import (
    AnalyticsFilter,
    OverviewAnalytics,
    ActionAnalyticsItem,
    FailureTypeAnalyticsItem,
    RetryCountAnalyticsItem,
    SubscriptionAnalyticsItem,
    TrendTimeBucketItem,
)
from analytics.service import analytics_service
from api.schemas import ErrorResponse

router = APIRouter(prefix="/analytics", tags=["Merchant Recovery Analytics"])


def _build_filter(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    action: Optional[RecoveryAction] = None,
    failure_type: Optional[FailureType] = None,
    is_subscription: Optional[bool] = None,
    retry_count: Optional[int] = None,
) -> AnalyticsFilter:
    """Helper to assemble and validate AnalyticsFilter."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date range: start_date '{start_date}' cannot be after end_date '{end_date}'.",
        )
    return AnalyticsFilter(
        start_date=start_date,
        end_date=end_date,
        action=action,
        failure_type=failure_type,
        is_subscription=is_subscription,
        retry_count=retry_count,
    )


@router.get(
    "/overview",
    response_model=OverviewAnalytics,
    status_code=status.HTTP_200_OK,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error or invalid date range"},
    },
)
async def get_analytics_overview(
    start_date: Optional[str] = Query(None, description="Start date (ISO 8601, e.g. '2026-08-01')"),
    end_date: Optional[str] = Query(None, description="End date (ISO 8601, e.g. '2026-08-31')"),
    action: Optional[RecoveryAction] = Query(None, description="Filter by recommended action"),
    failure_type: Optional[FailureType] = Query(None, description="Filter by diagnosed failure type"),
    is_subscription: Optional[bool] = Query(None, description="Filter by subscription status"),
    retry_count: Optional[int] = Query(None, ge=0, description="Filter by retry count"),
):
    """
    Returns high-level operational and financial recovery metrics across all persisted records.
    NOTE: These are observational production metrics and do not represent causal uplift.
    """
    filter_spec = _build_filter(start_date, end_date, action, failure_type, is_subscription, retry_count)
    try:
        return analytics_service.get_overview(filter_spec)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get(
    "/actions",
    response_model=List[ActionAnalyticsItem],
    status_code=status.HTTP_200_OK,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error or invalid date range"},
    },
)
async def get_analytics_actions(
    start_date: Optional[str] = Query(None, description="Start date (ISO 8601)"),
    end_date: Optional[str] = Query(None, description="End date (ISO 8601)"),
    failure_type: Optional[FailureType] = Query(None, description="Filter by diagnosed failure type"),
    is_subscription: Optional[bool] = Query(None, description="Filter by subscription status"),
    retry_count: Optional[int] = Query(None, ge=0, description="Filter by retry count"),
):
    """
    Returns observational metrics grouped by recovery action in deterministic order.
    """
    filter_spec = _build_filter(start_date, end_date, None, failure_type, is_subscription, retry_count)
    try:
        return analytics_service.get_actions_analytics(filter_spec)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get(
    "/failure-types",
    response_model=List[FailureTypeAnalyticsItem],
    status_code=status.HTTP_200_OK,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error or invalid date range"},
    },
)
async def get_analytics_failure_types(
    start_date: Optional[str] = Query(None, description="Start date (ISO 8601)"),
    end_date: Optional[str] = Query(None, description="End date (ISO 8601)"),
    action: Optional[RecoveryAction] = Query(None, description="Filter by recommended action"),
    is_subscription: Optional[bool] = Query(None, description="Filter by subscription status"),
    retry_count: Optional[int] = Query(None, ge=0, description="Filter by retry count"),
):
    """
    Returns observational recovery metrics grouped by diagnosed failure type.
    """
    filter_spec = _build_filter(start_date, end_date, action, None, is_subscription, retry_count)
    try:
        return analytics_service.get_failure_types_analytics(filter_spec)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get(
    "/retry-count",
    response_model=List[RetryCountAnalyticsItem],
    status_code=status.HTTP_200_OK,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error or invalid date range"},
    },
)
async def get_analytics_retry_count(
    start_date: Optional[str] = Query(None, description="Start date (ISO 8601)"),
    end_date: Optional[str] = Query(None, description="End date (ISO 8601)"),
    action: Optional[RecoveryAction] = Query(None, description="Filter by recommended action"),
    failure_type: Optional[FailureType] = Query(None, description="Filter by failure type"),
    is_subscription: Optional[bool] = Query(None, description="Filter by subscription status"),
):
    """
    Returns observational recovery metrics grouped by prior retry count.
    """
    filter_spec = _build_filter(start_date, end_date, action, failure_type, is_subscription, None)
    try:
        return analytics_service.get_retry_count_analytics(filter_spec)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get(
    "/subscriptions",
    response_model=List[SubscriptionAnalyticsItem],
    status_code=status.HTTP_200_OK,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error or invalid date range"},
    },
)
async def get_analytics_subscriptions(
    start_date: Optional[str] = Query(None, description="Start date (ISO 8601)"),
    end_date: Optional[str] = Query(None, description="End date (ISO 8601)"),
    action: Optional[RecoveryAction] = Query(None, description="Filter by recommended action"),
    failure_type: Optional[FailureType] = Query(None, description="Filter by failure type"),
    retry_count: Optional[int] = Query(None, ge=0, description="Filter by retry count"),
):
    """
    Returns observational recovery metrics grouped by payment segment ('one_off' vs 'subscription').
    """
    filter_spec = _build_filter(start_date, end_date, action, failure_type, None, retry_count)
    try:
        return analytics_service.get_subscriptions_analytics(filter_spec)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get(
    "/trends",
    response_model=List[TrendTimeBucketItem],
    status_code=status.HTTP_200_OK,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error or invalid date range"},
    },
)
async def get_analytics_trends(
    interval: str = Query("daily", description="Time interval bucket ('daily' or 'weekly')"),
    start_date: Optional[str] = Query(None, description="Start date (ISO 8601)"),
    end_date: Optional[str] = Query(None, description="End date (ISO 8601)"),
    action: Optional[RecoveryAction] = Query(None, description="Filter by recommended action"),
    failure_type: Optional[FailureType] = Query(None, description="Filter by failure type"),
    is_subscription: Optional[bool] = Query(None, description="Filter by subscription status"),
    retry_count: Optional[int] = Query(None, ge=0, description="Filter by retry count"),
):
    """
    Returns observational time-series recovery trends bucketed by time interval.
    """
    filter_spec = _build_filter(start_date, end_date, action, failure_type, is_subscription, retry_count)
    try:
        return analytics_service.get_trends(filter_spec, interval=interval)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
