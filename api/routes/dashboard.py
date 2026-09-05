"""
Merchant Recovery Command Center API Endpoints.
Provides observability, case queue management, case detail inspection,
and chronological audit timelines for merchant operations.
NON-NEGOTIABLE:
1. Observability and control surface only. Never makes autonomous decisions.
2. Analytics aggregation strictly reuses analytics.service domain semantics.
3. Financial quantities in API contracts are strictly 64-bit integer paise.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status

from simulator.config import FailureType, RecoveryAction
from analytics.models import AnalyticsFilter, OverviewAnalytics
from analytics.service import analytics_service
from api.services.operations_service import operations_service
from api.schemas import (
    ErrorResponse,
    PaginatedCasesResponse,
    RecoveryCaseSummaryItem,
    CaseDetailResponse,
    CaseDetailDecisionForecast,
    CaseDetailActionExecution,
    CaseDetailOutcomeSettlement,
    SubscriptionResponse,
    TimelineEventItem,
    CaseTimelineResponse,
)

router = APIRouter(tags=["Merchant Recovery Command Center"])


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
    "/dashboard/overview",
    response_model=OverviewAnalytics,
    status_code=status.HTTP_200_OK,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error or invalid date range"},
    },
)
async def get_dashboard_overview(
    start_date: Optional[str] = Query(None, description="Start date (ISO 8601, e.g. '2026-08-01')"),
    end_date: Optional[str] = Query(None, description="End date (ISO 8601, e.g. '2026-08-31')"),
    action: Optional[RecoveryAction] = Query(None, description="Filter by recommended action"),
    failure_type: Optional[FailureType] = Query(None, description="Filter by diagnosed failure type"),
    is_subscription: Optional[bool] = Query(None, description="Filter by subscription status"),
    retry_count: Optional[int] = Query(None, ge=0, description="Filter by retry count"),
):
    """
    Returns high-level operational and financial KPIs, conversion funnel, and authoritative
    settlement attribution (RecoverAI Net Recovered vs Provider Auto-Retry Gross).
    Reuses analytics_service as the single source of analytics truth.
    """
    filter_spec = _build_filter(start_date, end_date, action, failure_type, is_subscription, retry_count)
    try:
        return analytics_service.get_overview(filter_spec)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get(
    "/recovery/cases",
    response_model=PaginatedCasesResponse,
    status_code=status.HTTP_200_OK,
    responses={
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def list_recovery_cases(
    limit: int = Query(20, ge=1, le=100, description="Page limit (clamped to max 100)"),
    offset: int = Query(0, ge=0, description="Page offset (0-indexed)"),
    state: Optional[str] = Query(None, description="Filter by operational state (e.g. DECIDED, ACTION_EXECUTED, RECOVERED)"),
    action: Optional[RecoveryAction] = Query(None, description="Filter by recommended action"),
    failure_type: Optional[FailureType] = Query(None, description="Filter by diagnosed failure type"),
    is_subscription: Optional[bool] = Query(None, description="Filter by subscription status"),
    retry_count: Optional[int] = Query(None, ge=0, description="Filter by retry count"),
    search: Optional[str] = Query(None, min_length=1, max_length=100, description="Search case ID or customer ID"),
):
    """
    Returns a paginated, filterable queue of recovery cases.
    Enforces bounded pagination (limit <= 100). Returns strict integer paise amounts.
    """
    repo = operations_service.repository
    act_val = action.value if action else None
    ft_val = failure_type.value if failure_type else None

    cases, total_count = repo.list_cases(
        limit=limit,
        offset=offset,
        state=state,
        action=act_val,
        failure_type=ft_val,
        is_subscription=is_subscription,
        retry_count=retry_count,
        search=search,
    )

    items = [
        RecoveryCaseSummaryItem(
            case_id=c.case_id,
            customer_id=c.customer_id,
            amount_paise=c.amount_paise,
            current_state=c.current_state.value if hasattr(c.current_state, "value") else str(c.current_state),
            decision_id=c.decision_id,
            recommended_action=c.recommended_action.value if hasattr(c.recommended_action, "value") else str(c.recommended_action),
            payment_method=c.payment_method,
            is_subscription=c.is_subscription,
            failure_type=c.failure_type,
            retry_count=c.retry_count,
            subscription_id=c.subscription_id,
            billing_cycle_id=c.billing_cycle_id,
            recovery_source=c.recovery_source,
            resolution_source=c.resolution_source,
            outcome_status=c.outcome_status.value if c.outcome_status and hasattr(c.outcome_status, "value") else (str(c.outcome_status) if c.outcome_status else None),
            recovered_amount_paise=c.recovered_amount_paise,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in cases
    ]

    return PaginatedCasesResponse(
        items=items,
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/recovery/cases/{case_id}",
    response_model=CaseDetailResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse, "description": "Recovery case not found"},
    },
)
async def get_recovery_case_detail(case_id: str):
    """
    Retrieves full domain and operational detail for a single recovery case.
    Explicitly separates Model Forecast estimates from Authoritative Settled Outcomes.
    """
    repo = operations_service.repository
    detail = repo.get_case_detail(case_id)
    if not detail or not detail.get("case"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recovery case '{case_id}' was not found.",
        )

    case = detail["case"]
    case_summary = RecoveryCaseSummaryItem(
        case_id=case.case_id,
        customer_id=case.customer_id,
        amount_paise=case.amount_paise,
        current_state=case.current_state.value if hasattr(case.current_state, "value") else str(case.current_state),
        decision_id=case.decision_id,
        recommended_action=case.recommended_action.value if hasattr(case.recommended_action, "value") else str(case.recommended_action),
        payment_method=case.payment_method,
        is_subscription=case.is_subscription,
        failure_type=case.failure_type,
        retry_count=case.retry_count,
        subscription_id=case.subscription_id,
        billing_cycle_id=case.billing_cycle_id,
        recovery_source=case.recovery_source,
        resolution_source=case.resolution_source,
        outcome_status=case.outcome_status.value if case.outcome_status and hasattr(case.outcome_status, "value") else (str(case.outcome_status) if case.outcome_status else None),
        recovered_amount_paise=case.recovered_amount_paise,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )

    decision_forecast = None
    if detail.get("decision"):
        d = detail["decision"]
        decision_forecast = CaseDetailDecisionForecast(
            decision_id=d.decision_id,
            recommended_action=d.recommended_action.value if hasattr(d.recommended_action, "value") else str(d.recommended_action),
            recovery_probability=d.recommended_action_recovery_probability,
            expected_gross_recovery_paise=d.expected_gross_recovery_paise,
            action_cost_paise=d.action_cost_paise,
            expected_net_recovery_paise=d.expected_net_recovery_paise,
            decision_margin_paise=d.decision_margin_paise,
            explanation=d.explanation,
            model_family=d.model_family,
            created_at=d.created_at,
        )

    action_execution = None
    if detail.get("action"):
        a = detail["action"]
        action_execution = CaseDetailActionExecution(
            action_id=a.action_id,
            action=a.action.value if hasattr(a.action, "value") else str(a.action),
            status=a.status.value if hasattr(a.status, "value") else str(a.status),
            cost_paise=a.cost_paise,
            provider_reference=a.provider_reference,
            error_message=a.error_message,
            executed_at=a.executed_at,
            idempotency_key=a.idempotency_key,
        )

    outcome_settlement = None
    if detail.get("outcome"):
        o = detail["outcome"]
        outcome_settlement = CaseDetailOutcomeSettlement(
            event_id=o.event_id,
            outcome_status=o.outcome_status.value if hasattr(o.outcome_status, "value") else str(o.outcome_status),
            recovered_amount_paise=o.recovered_amount_paise,
            resolution_source=o.resolution_source,
            provider_reference=o.provider_reference,
            metadata=o.metadata or {},
            event_timestamp=o.event_timestamp,
            created_at=o.created_at,
        )

    subscription = None
    if detail.get("subscription"):
        s = detail["subscription"]
        subscription = SubscriptionResponse(
            subscription_id=s.subscription_id,
            customer_id=s.customer_id,
            plan_id=s.plan_id,
            status=s.status.value if hasattr(s.status, "value") else str(s.status),
            current_cycle=s.current_cycle,
            total_cycles=s.total_cycles,
            amount_due_paise=s.amount_due_paise,
            amount_due_inr=s.amount_due_paise / 100.0,
            currency=s.currency,
            charge_attempt_count=s.charge_attempt_count,
            next_charge_at=s.next_charge_at,
            last_case_id=s.last_case_id,
            is_recoverable=s.is_recoverable,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )

    return CaseDetailResponse(
        case=case_summary,
        decision_forecast=decision_forecast,
        action_execution=action_execution,
        outcome_settlement=outcome_settlement,
        subscription=subscription,
    )


@router.get(
    "/recovery/cases/{case_id}/timeline",
    response_model=CaseTimelineResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse, "description": "Recovery case not found"},
    },
)
async def get_recovery_case_timeline(case_id: str):
    """
    Returns the strict, chronological audit timeline for a recovery case.
    GUARANTEE: Every timeline event is derived strictly from real, persisted records.
    Never synthesizes unpersisted events.
    """
    repo = operations_service.repository
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recovery case '{case_id}' was not found.",
        )

    raw_events = repo.get_case_timeline(case_id)
    items = [
        TimelineEventItem(
            event_id=e["event_id"],
            stage=e["stage"],
            timestamp=e["timestamp"],
            title=e["title"],
            description=e["description"],
            status=e["status"],
            metadata=e.get("metadata", {}),
        )
        for e in raw_events
    ]

    return CaseTimelineResponse(
        case_id=case_id,
        events=items,
    )
