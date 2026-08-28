"""
Analytics service layer for RecoverAI.
Connects API routes to the analytics repository.
"""

from typing import List, Optional

from recovery.repository import RecoveryRepository
from analytics.models import (
    AnalyticsFilter,
    OverviewAnalytics,
    ActionAnalyticsItem,
    FailureTypeAnalyticsItem,
    RetryCountAnalyticsItem,
    SubscriptionAnalyticsItem,
    TrendTimeBucketItem,
)
from analytics.repository import AnalyticsRepository


class AnalyticsService:
    """
    Business service providing observational merchant analytics.
    Guarantees:
    1. Purely observational production metrics (no causal claims).
    2. Input validation for date ranges and filters.
    3. Thread-safe queries via repository abstraction.
    """

    def __init__(self, analytics_repo: Optional[AnalyticsRepository] = None):
        if analytics_repo is None:
            # Default to global operations repository
            from api.services.operations_service import operations_service
            self.repository = AnalyticsRepository(operations_service.repository)
        else:
            self.repository = analytics_repo

    def get_overview(self, filter_spec: Optional[AnalyticsFilter] = None) -> OverviewAnalytics:
        """Computes high-level overview metrics."""
        return self.repository.get_overview(filter_spec)

    def get_actions_analytics(self, filter_spec: Optional[AnalyticsFilter] = None) -> List[ActionAnalyticsItem]:
        """Computes action-level breakdown metrics."""
        return self.repository.get_actions_analytics(filter_spec)

    def get_failure_types_analytics(self, filter_spec: Optional[AnalyticsFilter] = None) -> List[FailureTypeAnalyticsItem]:
        """Computes failure-type breakdown metrics."""
        return self.repository.get_failure_types_analytics(filter_spec)

    def get_retry_count_analytics(self, filter_spec: Optional[AnalyticsFilter] = None) -> List[RetryCountAnalyticsItem]:
        """Computes retry-count breakdown metrics."""
        return self.repository.get_retry_count_analytics(filter_spec)

    def get_subscriptions_analytics(self, filter_spec: Optional[AnalyticsFilter] = None) -> List[SubscriptionAnalyticsItem]:
        """Computes subscription segment breakdown metrics."""
        return self.repository.get_subscriptions_analytics(filter_spec)

    def get_trends(
        self,
        filter_spec: Optional[AnalyticsFilter] = None,
        interval: str = "daily",
    ) -> List[TrendTimeBucketItem]:
        """Computes time-series trend metrics."""
        if interval not in ("daily", "weekly"):
            raise ValueError(f"Unsupported time interval '{interval}'. Supported intervals: 'daily', 'weekly'.")
        return self.repository.get_trends(filter_spec, interval=interval)


# Global analytics service instance
analytics_service = AnalyticsService()
