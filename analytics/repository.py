"""
SQLite repository queries for RecoverAI Analytics.
Executes efficient, indexed aggregations across cases, decisions, actions, and outcomes.
"""

from datetime import datetime, timezone
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from simulator.config import FailureType, RecoveryAction
from recovery.repository import RecoveryRepository
from analytics.models import (
    AnalyticsFilter,
    OverviewAnalytics,
    FunnelAnalytics,
    AttributionAnalytics,
    ActionAnalyticsItem,
    FailureTypeAnalyticsItem,
    RetryCountAnalyticsItem,
    SubscriptionAnalyticsItem,
    TrendTimeBucketItem,
)
from analytics.metrics import (
    calculate_rate,
    calculate_recovery_rate,
    paise_to_inr,
    calculate_net_paise,
    calculate_average_paise,
)

# Deterministic ordering specifications
ACTION_ORDER = [
    RecoveryAction.NO_ACTION,
    RecoveryAction.RETRY,
    RecoveryAction.PAYMENT_LINK,
    RecoveryAction.REMINDER,
    RecoveryAction.ESCALATE,
]

FAILURE_TYPE_ORDER = [
    FailureType.INSUFFICIENT_FUNDS,
    FailureType.INVALID_PAYMENT_METHOD,
    FailureType.TEMPORARY_FAILURE,
    FailureType.UNKNOWN_FAILURE,
]


class AnalyticsRepository:
    """
    Data access repository for analytical aggregations.
    Reuses the thread-safe connection from the underlying RecoveryRepository.
    """

    def __init__(self, recovery_repo: RecoveryRepository):
        self.recovery_repo = recovery_repo

    def _get_connection(self) -> sqlite3.Connection:
        return self.recovery_repo._get_connection()

    def _build_where_clause(
        self,
        filter_spec: Optional[AnalyticsFilter],
        table_alias: str = "c",
    ) -> Tuple[str, List[Any]]:
        """
        Constructs SQL WHERE clause and parameter list from filter specification.
        Validates date ranges.
        """
        if filter_spec is None:
            return "", []

        clauses = []
        params: List[Any] = []

        if filter_spec.start_date and filter_spec.end_date:
            if filter_spec.start_date > filter_spec.end_date:
                raise ValueError(
                    f"Invalid date range: start_date '{filter_spec.start_date}' cannot be after end_date '{filter_spec.end_date}'."
                )

        if filter_spec.start_date:
            clauses.append(f"{table_alias}.created_at >= ?")
            params.append(filter_spec.start_date)

        if filter_spec.end_date:
            # Match up to end of date string (e.g. if '2026-08-31', match up to '2026-08-31T23:59:59.999999')
            end_val = filter_spec.end_date
            if len(end_val) == 10:  # YYYY-MM-DD
                end_val = f"{end_val}T23:59:59.999999Z"
            clauses.append(f"{table_alias}.created_at <= ?")
            params.append(end_val)

        if filter_spec.action:
            act_val = filter_spec.action.value if hasattr(filter_spec.action, "value") else str(filter_spec.action)
            clauses.append(f"{table_alias}.recommended_action = ?")
            params.append(act_val)

        if filter_spec.failure_type:
            ft_val = filter_spec.failure_type.value if hasattr(filter_spec.failure_type, "value") else str(filter_spec.failure_type)
            clauses.append(f"{table_alias}.failure_type = ?")
            params.append(ft_val)

        if filter_spec.is_subscription is not None:
            clauses.append(f"{table_alias}.is_subscription = ?")
            params.append(1 if filter_spec.is_subscription else 0)

        if filter_spec.retry_count is not None:
            clauses.append(f"{table_alias}.retry_count = ?")
            params.append(filter_spec.retry_count)

        if not clauses:
            return "", []

        return "WHERE " + " AND ".join(clauses), params

    def get_overview(self, filter_spec: Optional[AnalyticsFilter] = None) -> OverviewAnalytics:
        """
        Computes high-level operational and financial summary.
        """
        conn = self._get_connection()
        where_sql, params = self._build_where_clause(filter_spec, table_alias="c")

        # 1. Cases & Decisions aggregates
        cur = conn.execute(
            f"""
            SELECT
                COUNT(c.case_id) as total_cases,
                COALESCE(SUM(c.amount_paise), 0) as total_amount_at_risk_paise,
                SUM(CASE WHEN c.current_state NOT IN ('RECOVERED', 'NOT_RECOVERED') THEN 1 ELSE 0 END) as pending_cases
            FROM cases c
            {where_sql};
            """,
            params,
        )
        row = cur.fetchone()
        total_cases = row["total_cases"] or 0
        total_amount_at_risk_paise = row["total_amount_at_risk_paise"] or 0
        pending_cases = row["pending_cases"] or 0
        decisions_made = total_cases  # Each case corresponds to 1 decision

        # 2. Actions aggregates
        cur = conn.execute(
            f"""
            SELECT
                COUNT(a.action_id) as actions_attempted,
                SUM(CASE WHEN a.status = 'EXECUTED' THEN 1 ELSE 0 END) as actions_executed,
                SUM(CASE WHEN a.status = 'FAILED' THEN 1 ELSE 0 END) as execution_failures,
                COALESCE(SUM(CASE WHEN a.status = 'EXECUTED' THEN a.cost_paise ELSE 0 END), 0) as total_action_cost_paise
            FROM cases c
            JOIN actions a ON c.case_id = a.case_id
            {where_sql};
            """,
            params,
        )
        row = cur.fetchone()
        actions_attempted = row["actions_attempted"] or 0
        actions_executed = row["actions_executed"] or 0
        execution_failures = row["execution_failures"] or 0
        total_action_cost_paise = row["total_action_cost_paise"] or 0

        # 3. Outcomes aggregates with authoritative attribution
        cur = conn.execute(
            f"""
            SELECT
                SUM(CASE WHEN o.outcome_status = 'recovered' THEN 1 ELSE 0 END) as recovered_cases,
                SUM(CASE WHEN o.outcome_status = 'not_recovered' THEN 1 ELSE 0 END) as not_recovered_cases,
                COALESCE(SUM(CASE WHEN o.outcome_status = 'recovered' THEN o.recovered_amount_paise ELSE 0 END), 0) as gross_recovered_paise,
                COALESCE(SUM(CASE WHEN o.outcome_status = 'recovered' AND (o.resolution_source = 'recoverai_intervention' OR o.resolution_source IS NULL) THEN o.recovered_amount_paise ELSE 0 END), 0) as recoverai_gross_paise,
                COALESCE(SUM(CASE WHEN o.outcome_status = 'recovered' AND o.resolution_source = 'provider_auto_retry' THEN o.recovered_amount_paise ELSE 0 END), 0) as provider_gross_paise,
                SUM(CASE WHEN o.outcome_status = 'recovered' AND (o.resolution_source = 'recoverai_intervention' OR o.resolution_source IS NULL) THEN 1 ELSE 0 END) as recoverai_rec_count,
                SUM(CASE WHEN o.outcome_status = 'recovered' AND o.resolution_source = 'provider_auto_retry' THEN 1 ELSE 0 END) as provider_rec_count
            FROM cases c
            JOIN outcomes o ON c.case_id = o.case_id
            {where_sql};
            """,
            params,
        )
        row = cur.fetchone()
        recovered_cases = row["recovered_cases"] or 0
        not_recovered_cases = row["not_recovered_cases"] or 0
        gross_recovered_paise = row["gross_recovered_paise"] or 0
        recoverai_gross_recovered_paise = row["recoverai_gross_paise"] or 0
        provider_gross_recovered_paise = row["provider_gross_paise"] or 0
        recoverai_rec_count = row["recoverai_rec_count"] or 0
        provider_rec_count = row["provider_rec_count"] or 0

        recoverai_net_recovered_paise = calculate_net_paise(recoverai_gross_recovered_paise, total_action_cost_paise)
        net_recovered_paise = calculate_net_paise(gross_recovered_paise, total_action_cost_paise)
        recovery_rate = calculate_recovery_rate(recovered_cases, not_recovered_cases)
        execution_success_rate = calculate_rate(actions_executed, actions_attempted)
        execution_failure_rate = calculate_rate(execution_failures, actions_attempted)

        unresolved_cases = max(0, total_cases - recovered_cases)

        funnel = FunnelAnalytics(
            cases_at_risk=total_cases,
            decisions_evaluated=decisions_made,
            interventions_dispatched=actions_attempted,
            successful_executions=actions_executed,
            recovered_outcomes=recovered_cases,
        )

        attribution = AttributionAnalytics(
            recoverai_intervention_recovered_cases=recoverai_rec_count,
            provider_auto_retry_recovered_cases=provider_rec_count,
            unresolved_cases=unresolved_cases,
        )

        now_ts = datetime.now(timezone.utc).isoformat()

        return OverviewAnalytics(
            total_cases=total_cases,
            decisions_made=decisions_made,
            actions_attempted=actions_attempted,
            actions_executed=actions_executed,
            execution_failures=execution_failures,
            recovered_cases=recovered_cases,
            not_recovered_cases=not_recovered_cases,
            pending_cases=pending_cases,
            recovery_rate=recovery_rate,
            execution_success_rate=execution_success_rate,
            execution_failure_rate=execution_failure_rate,
            total_amount_at_risk_paise=total_amount_at_risk_paise,
            total_amount_at_risk_inr=paise_to_inr(total_amount_at_risk_paise),
            gross_recovered_paise=gross_recovered_paise,
            gross_recovered_inr=paise_to_inr(gross_recovered_paise),
            total_action_cost_paise=total_action_cost_paise,
            total_action_cost_inr=paise_to_inr(total_action_cost_paise),
            net_recovered_paise=net_recovered_paise,
            net_recovered_inr=paise_to_inr(net_recovered_paise),
            recoverai_gross_recovered_paise=recoverai_gross_recovered_paise,
            recoverai_gross_recovered_inr=paise_to_inr(recoverai_gross_recovered_paise),
            provider_gross_recovered_paise=provider_gross_recovered_paise,
            provider_gross_recovered_inr=paise_to_inr(provider_gross_recovered_paise),
            recoverai_net_recovered_paise=recoverai_net_recovered_paise,
            recoverai_net_recovered_inr=paise_to_inr(recoverai_net_recovered_paise),
            funnel=funnel,
            attribution=attribution,
            timestamp=now_ts,
        )

    def get_actions_analytics(self, filter_spec: Optional[AnalyticsFilter] = None) -> List[ActionAnalyticsItem]:
        """
        Returns observational metrics grouped by action category in deterministic order.
        """
        conn = self._get_connection()
        where_sql, params = self._build_where_clause(filter_spec, table_alias="c")

        cur = conn.execute(
            f"""
            SELECT
                c.recommended_action as action_name,
                COUNT(DISTINCT c.case_id) as decisions_count,
                COUNT(a.action_id) as attempts_count,
                SUM(CASE WHEN a.status = 'EXECUTED' THEN 1 ELSE 0 END) as executed_count,
                SUM(CASE WHEN a.status = 'FAILED' THEN 1 ELSE 0 END) as failures_count,
                SUM(CASE WHEN o.outcome_status = 'recovered' THEN 1 ELSE 0 END) as recovered_count,
                SUM(CASE WHEN o.outcome_status = 'not_recovered' THEN 1 ELSE 0 END) as not_recovered_count,
                COALESCE(SUM(CASE WHEN o.outcome_status = 'recovered' THEN o.recovered_amount_paise ELSE 0 END), 0) as gross_paise,
                COALESCE(SUM(CASE WHEN a.status = 'EXECUTED' THEN a.cost_paise ELSE 0 END), 0) as cost_paise
            FROM cases c
            LEFT JOIN actions a ON c.case_id = a.case_id
            LEFT JOIN outcomes o ON c.case_id = o.case_id
            {where_sql}
            GROUP BY c.recommended_action;
            """,
            params,
        )
        data_by_action = {row["action_name"]: row for row in cur.fetchall()}

        items: List[ActionAnalyticsItem] = []
        for act in ACTION_ORDER:
            row = data_by_action.get(act.value)
            if row:
                decisions = row["decisions_count"] or 0
                attempts = row["attempts_count"] or 0
                executed = row["executed_count"] or 0
                failures = row["failures_count"] or 0
                rec = row["recovered_count"] or 0
                not_rec = row["not_recovered_count"] or 0
                gross = row["gross_paise"] or 0
                cost = row["cost_paise"] or 0
            else:
                decisions = attempts = executed = failures = rec = not_rec = gross = cost = 0

            net = calculate_net_paise(gross, cost)
            rec_rate = calculate_recovery_rate(rec, not_rec)
            avg_gross = calculate_average_paise(gross, rec)

            items.append(
                ActionAnalyticsItem(
                    action=act,
                    decisions=decisions,
                    execution_attempts=attempts,
                    successful_executions=executed,
                    execution_failures=failures,
                    recovered_cases=rec,
                    not_recovered_cases=not_rec,
                    recovery_rate=rec_rate,
                    gross_recovered_paise=gross,
                    gross_recovered_inr=paise_to_inr(gross),
                    action_cost_paise=cost,
                    action_cost_inr=paise_to_inr(cost),
                    net_recovered_paise=net,
                    net_recovered_inr=paise_to_inr(net),
                    average_recovered_amount_paise=avg_gross,
                    average_recovered_amount_inr=paise_to_inr(avg_gross),
                )
            )

        return items

    def get_failure_types_analytics(self, filter_spec: Optional[AnalyticsFilter] = None) -> List[FailureTypeAnalyticsItem]:
        """
        Returns observational recovery metrics grouped by failure type.
        """
        conn = self._get_connection()
        where_sql, params = self._build_where_clause(filter_spec, table_alias="c")

        cur = conn.execute(
            f"""
            SELECT
                c.failure_type as ft_name,
                COUNT(DISTINCT c.case_id) as cases_count,
                SUM(CASE WHEN a.status = 'EXECUTED' THEN 1 ELSE 0 END) as executed_count,
                SUM(CASE WHEN o.outcome_status = 'recovered' THEN 1 ELSE 0 END) as recovered_count,
                SUM(CASE WHEN o.outcome_status = 'not_recovered' THEN 1 ELSE 0 END) as not_recovered_count,
                COALESCE(SUM(CASE WHEN o.outcome_status = 'recovered' THEN o.recovered_amount_paise ELSE 0 END), 0) as gross_paise,
                COALESCE(SUM(CASE WHEN a.status = 'EXECUTED' THEN a.cost_paise ELSE 0 END), 0) as cost_paise
            FROM cases c
            LEFT JOIN actions a ON c.case_id = a.case_id
            LEFT JOIN outcomes o ON c.case_id = o.case_id
            {where_sql}
            GROUP BY c.failure_type;
            """,
            params,
        )
        data_by_ft = {row["ft_name"]: row for row in cur.fetchall()}

        items: List[FailureTypeAnalyticsItem] = []
        for ft in FAILURE_TYPE_ORDER:
            row = data_by_ft.get(ft.value)
            if row:
                cases = row["cases_count"] or 0
                executed = row["executed_count"] or 0
                rec = row["recovered_count"] or 0
                not_rec = row["not_recovered_count"] or 0
                gross = row["gross_paise"] or 0
                cost = row["cost_paise"] or 0
            else:
                cases = executed = rec = not_rec = gross = cost = 0

            net = calculate_net_paise(gross, cost)
            rec_rate = calculate_recovery_rate(rec, not_rec)

            items.append(
                FailureTypeAnalyticsItem(
                    failure_type=ft,
                    cases=cases,
                    actions_executed=executed,
                    recovered_cases=rec,
                    not_recovered_cases=not_rec,
                    recovery_rate=rec_rate,
                    gross_recovered_paise=gross,
                    gross_recovered_inr=paise_to_inr(gross),
                    action_cost_paise=cost,
                    action_cost_inr=paise_to_inr(cost),
                    net_recovered_paise=net,
                    net_recovered_inr=paise_to_inr(net),
                )
            )

        return items

    def get_retry_count_analytics(self, filter_spec: Optional[AnalyticsFilter] = None) -> List[RetryCountAnalyticsItem]:
        """
        Returns observational metrics grouped by retry count (0, 1, 2, ...).
        """
        conn = self._get_connection()
        where_sql, params = self._build_where_clause(filter_spec, table_alias="c")

        cur = conn.execute(
            f"""
            SELECT
                c.retry_count as rc,
                COUNT(DISTINCT c.case_id) as cases_count,
                SUM(CASE WHEN a.status = 'EXECUTED' THEN 1 ELSE 0 END) as executed_count,
                SUM(CASE WHEN o.outcome_status = 'recovered' THEN 1 ELSE 0 END) as recovered_count,
                SUM(CASE WHEN o.outcome_status = 'not_recovered' THEN 1 ELSE 0 END) as not_recovered_count,
                COALESCE(SUM(CASE WHEN o.outcome_status = 'recovered' THEN o.recovered_amount_paise ELSE 0 END), 0) as gross_paise,
                COALESCE(SUM(CASE WHEN a.status = 'EXECUTED' THEN a.cost_paise ELSE 0 END), 0) as cost_paise
            FROM cases c
            LEFT JOIN actions a ON c.case_id = a.case_id
            LEFT JOIN outcomes o ON c.case_id = o.case_id
            {where_sql}
            GROUP BY c.retry_count
            ORDER BY c.retry_count ASC;
            """,
            params,
        )
        rows = cur.fetchall()
        items: List[RetryCountAnalyticsItem] = []

        for row in rows:
            rc = row["rc"]
            cases = row["cases_count"] or 0
            executed = row["executed_count"] or 0
            rec = row["recovered_count"] or 0
            not_rec = row["not_recovered_count"] or 0
            gross = row["gross_paise"] or 0
            cost = row["cost_paise"] or 0
            net = calculate_net_paise(gross, cost)
            rec_rate = calculate_recovery_rate(rec, not_rec)

            items.append(
                RetryCountAnalyticsItem(
                    retry_count=rc,
                    cases=cases,
                    actions_executed=executed,
                    recovered_cases=rec,
                    not_recovered_cases=not_rec,
                    recovery_rate=rec_rate,
                    gross_recovered_paise=gross,
                    gross_recovered_inr=paise_to_inr(gross),
                    action_cost_paise=cost,
                    action_cost_inr=paise_to_inr(cost),
                    net_recovered_paise=net,
                    net_recovered_inr=paise_to_inr(net),
                )
            )

        return items

    def get_subscriptions_analytics(self, filter_spec: Optional[AnalyticsFilter] = None) -> List[SubscriptionAnalyticsItem]:
        """
        Returns observational metrics grouped by subscription segment ('one_off' vs 'subscription').
        """
        conn = self._get_connection()
        where_sql, params = self._build_where_clause(filter_spec, table_alias="c")

        cur = conn.execute(
            f"""
            SELECT
                c.is_subscription as is_sub,
                COUNT(DISTINCT c.case_id) as cases_count,
                SUM(CASE WHEN a.status = 'EXECUTED' THEN 1 ELSE 0 END) as executed_count,
                SUM(CASE WHEN o.outcome_status = 'recovered' THEN 1 ELSE 0 END) as recovered_count,
                SUM(CASE WHEN o.outcome_status = 'not_recovered' THEN 1 ELSE 0 END) as not_recovered_count,
                COALESCE(SUM(CASE WHEN o.outcome_status = 'recovered' THEN o.recovered_amount_paise ELSE 0 END), 0) as gross_paise,
                COALESCE(SUM(CASE WHEN a.status = 'EXECUTED' THEN a.cost_paise ELSE 0 END), 0) as cost_paise
            FROM cases c
            LEFT JOIN actions a ON c.case_id = a.case_id
            LEFT JOIN outcomes o ON c.case_id = o.case_id
            {where_sql}
            GROUP BY c.is_subscription;
            """,
            params,
        )
        data_by_sub = {row["is_sub"]: row for row in cur.fetchall()}

        segments = [("one_off", 0), ("subscription", 1)]
        items: List[SubscriptionAnalyticsItem] = []

        for seg_name, seg_val in segments:
            row = data_by_sub.get(seg_val)
            if row:
                cases = row["cases_count"] or 0
                executed = row["executed_count"] or 0
                rec = row["recovered_count"] or 0
                not_rec = row["not_recovered_count"] or 0
                gross = row["gross_paise"] or 0
                cost = row["cost_paise"] or 0
            else:
                cases = executed = rec = not_rec = gross = cost = 0

            net = calculate_net_paise(gross, cost)
            rec_rate = calculate_recovery_rate(rec, not_rec)

            items.append(
                SubscriptionAnalyticsItem(
                    segment=seg_name,
                    cases=cases,
                    actions_executed=executed,
                    recovered_cases=rec,
                    not_recovered_cases=not_rec,
                    recovery_rate=rec_rate,
                    gross_recovered_paise=gross,
                    gross_recovered_inr=paise_to_inr(gross),
                    action_cost_paise=cost,
                    action_cost_inr=paise_to_inr(cost),
                    net_recovered_paise=net,
                    net_recovered_inr=paise_to_inr(net),
                )
            )

        return items

    def get_trends(
        self,
        filter_spec: Optional[AnalyticsFilter] = None,
        interval: str = "daily",
    ) -> List[TrendTimeBucketItem]:
        """
        Returns time-series metrics bucketed by time interval ('daily' or 'weekly').
        """
        conn = self._get_connection()
        where_sql, params = self._build_where_clause(filter_spec, table_alias="c")

        time_expr = "substr(c.created_at, 1, 10)" if interval == "daily" else "strftime('%Y-W%W', c.created_at)"

        cur = conn.execute(
            f"""
            SELECT
                {time_expr} as bucket,
                COUNT(DISTINCT c.case_id) as cases_count,
                COUNT(DISTINCT c.decision_id) as decisions_count,
                SUM(CASE WHEN a.status = 'EXECUTED' THEN 1 ELSE 0 END) as executed_count,
                SUM(CASE WHEN a.status = 'FAILED' THEN 1 ELSE 0 END) as failures_count,
                SUM(CASE WHEN o.outcome_status = 'recovered' THEN 1 ELSE 0 END) as recovered_count,
                SUM(CASE WHEN o.outcome_status = 'not_recovered' THEN 1 ELSE 0 END) as not_recovered_count,
                COALESCE(SUM(CASE WHEN o.outcome_status = 'recovered' THEN o.recovered_amount_paise ELSE 0 END), 0) as gross_paise,
                COALESCE(SUM(CASE WHEN a.status = 'EXECUTED' THEN a.cost_paise ELSE 0 END), 0) as cost_paise
            FROM cases c
            LEFT JOIN actions a ON c.case_id = a.case_id
            LEFT JOIN outcomes o ON c.case_id = o.case_id
            {where_sql}
            GROUP BY bucket
            ORDER BY bucket ASC;
            """,
            params,
        )
        rows = cur.fetchall()
        items: List[TrendTimeBucketItem] = []

        for row in rows:
            bucket = row["bucket"] or "unknown"
            cases = row["cases_count"] or 0
            decisions = row["decisions_count"] or 0
            executed = row["executed_count"] or 0
            failures = row["failures_count"] or 0
            rec = row["recovered_count"] or 0
            not_rec = row["not_recovered_count"] or 0
            gross = row["gross_paise"] or 0
            cost = row["cost_paise"] or 0
            net = calculate_net_paise(gross, cost)

            items.append(
                TrendTimeBucketItem(
                    time_bucket=bucket,
                    cases=cases,
                    decisions=decisions,
                    actions_executed=executed,
                    execution_failures=failures,
                    recovered_cases=rec,
                    not_recovered_cases=not_rec,
                    gross_recovered_paise=gross,
                    gross_recovered_inr=paise_to_inr(gross),
                    action_cost_paise=cost,
                    action_cost_inr=paise_to_inr(cost),
                    net_recovered_paise=net,
                    net_recovered_inr=paise_to_inr(net),
                )
            )

        return items
