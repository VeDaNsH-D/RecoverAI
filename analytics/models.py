"""
Domain models and schema definitions for RecoverAI Merchant Recovery Analytics.
All financial metrics are computed in exact integer paise with INR representations for presentation.
NON-NEGOTIABLE: All metrics are descriptive and observational. Zero causal claims.
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import FailureType, RecoveryAction


class AnalyticsFilter(BaseModel):
    """
    Filter criteria for observational recovery analytics queries.
    Closed schema (extra='forbid').
    """
    model_config = ConfigDict(extra="forbid")

    start_date: Optional[str] = Field(default=None, description="Start date (ISO 8601 string, e.g. '2026-08-01')")
    end_date: Optional[str] = Field(default=None, description="End date (ISO 8601 string, e.g. '2026-08-31')")
    action: Optional[RecoveryAction] = Field(default=None, description="Filter by recovery action")
    failure_type: Optional[FailureType] = Field(default=None, description="Filter by failure diagnostic type")
    is_subscription: Optional[bool] = Field(default=None, description="Filter by subscription status")
    retry_count: Optional[int] = Field(default=None, ge=0, description="Filter by retry count")


class OverviewAnalytics(BaseModel):
    """
    High-level operational and financial summary of merchant recovery performance.
    """
    model_config = ConfigDict(frozen=True)

    total_cases: int
    decisions_made: int
    actions_attempted: int
    actions_executed: int
    execution_failures: int
    recovered_cases: int
    not_recovered_cases: int
    pending_cases: int

    recovery_rate: float
    execution_success_rate: float
    execution_failure_rate: float

    total_amount_at_risk_paise: int
    total_amount_at_risk_inr: float
    gross_recovered_paise: int
    gross_recovered_inr: float
    total_action_cost_paise: int
    total_action_cost_inr: float
    net_recovered_paise: int
    net_recovered_inr: float

    timestamp: str


class ActionAnalyticsItem(BaseModel):
    """
    Observational analytics record for a single recovery action.
    """
    model_config = ConfigDict(frozen=True)

    action: RecoveryAction
    decisions: int
    execution_attempts: int
    successful_executions: int
    execution_failures: int
    recovered_cases: int
    not_recovered_cases: int
    recovery_rate: float
    gross_recovered_paise: int
    gross_recovered_inr: float
    action_cost_paise: int
    action_cost_inr: float
    net_recovered_paise: int
    net_recovered_inr: float
    average_recovered_amount_paise: int
    average_recovered_amount_inr: float


class FailureTypeAnalyticsItem(BaseModel):
    """
    Observational recovery metrics grouped by diagnosed failure type.
    """
    model_config = ConfigDict(frozen=True)

    failure_type: FailureType
    cases: int
    actions_executed: int
    recovered_cases: int
    not_recovered_cases: int
    recovery_rate: float
    gross_recovered_paise: int
    gross_recovered_inr: float
    action_cost_paise: int
    action_cost_inr: float
    net_recovered_paise: int
    net_recovered_inr: float


class RetryCountAnalyticsItem(BaseModel):
    """
    Observational recovery metrics grouped by prior retry count.
    """
    model_config = ConfigDict(frozen=True)

    retry_count: int
    cases: int
    actions_executed: int
    recovered_cases: int
    not_recovered_cases: int
    recovery_rate: float
    gross_recovered_paise: int
    gross_recovered_inr: float
    action_cost_paise: int
    action_cost_inr: float
    net_recovered_paise: int
    net_recovered_inr: float


class SubscriptionAnalyticsItem(BaseModel):
    """
    Observational recovery metrics grouped by payment segment (subscription vs one-off).
    """
    model_config = ConfigDict(frozen=True)

    segment: str  # "subscription" or "one_off"
    cases: int
    actions_executed: int
    recovered_cases: int
    not_recovered_cases: int
    recovery_rate: float
    gross_recovered_paise: int
    gross_recovered_inr: float
    action_cost_paise: int
    action_cost_inr: float
    net_recovered_paise: int
    net_recovered_inr: float


class TrendTimeBucketItem(BaseModel):
    """
    Observational recovery metrics bucketed by time interval.
    """
    model_config = ConfigDict(frozen=True)

    time_bucket: str
    cases: int
    decisions: int
    actions_executed: int
    execution_failures: int
    recovered_cases: int
    not_recovered_cases: int
    gross_recovered_paise: int
    gross_recovered_inr: float
    action_cost_paise: int
    action_cost_inr: float
    net_recovered_paise: int
    net_recovered_inr: float
