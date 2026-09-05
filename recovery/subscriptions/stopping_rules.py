"""
Subscription-specific stopping rules and intervention bounds for RecoverAI.
Guarantees deterministic stopping, customer spam prevention, and lifecycle integrity.
"""

from typing import Optional
from pydantic import BaseModel, Field

from simulator.config import RecoveryAction
from recovery.models import CaseState, RecoveryCaseRecord
from recovery.subscriptions.models import RazorpaySubscriptionStatus, SubscriptionRecord


class StoppingRuleResult(BaseModel):
    """Result of evaluating subscription stopping rules."""
    should_stop: bool = Field(..., description="Whether recovery intervention must be suppressed / stopped")
    reason: Optional[str] = Field(default=None, description="Stopping rationale if suppressed")


def evaluate_subscription_stopping_rules(
    subscription: Optional[SubscriptionRecord],
    case: Optional[RecoveryCaseRecord],
    action: RecoveryAction,
) -> StoppingRuleResult:
    """
    Evaluates hard deterministic stopping rules for subscription recovery.
    
    Stopping Conditions:
    1. Subscription is cancelled or completed (never intervene on dead subscriptions).
    2. Case is already in terminal state (RECOVERED or NOT_RECOVERED).
    3. An action was already executed for this billing cycle (idempotent single intervention per cycle).
    4. Selected decision is NO_ACTION.
    5. Case amount is 0 (nothing at risk).
    """
    # 1. Terminal subscription status
    if subscription is not None:
        if subscription.status == RazorpaySubscriptionStatus.CANCELLED:
            return StoppingRuleResult(
                should_stop=True,
                reason="Subscription is cancelled. Interventions prohibited.",
            )
        if subscription.status == RazorpaySubscriptionStatus.COMPLETED:
            return StoppingRuleResult(
                should_stop=True,
                reason="Subscription is completed. No outstanding cycles remain.",
            )

    # 2. Existing recovery case checks
    if case is not None:
        if case.current_state in (CaseState.RECOVERED, CaseState.NOT_RECOVERED):
            return StoppingRuleResult(
                should_stop=True,
                reason=f"Recovery case '{case.case_id}' is already in terminal state '{case.current_state.value}'.",
            )
        if case.current_state == CaseState.ACTION_EXECUTED:
            return StoppingRuleResult(
                should_stop=True,
                reason=f"Recovery case '{case.case_id}' already has an executed action '{case.last_action_id}'. Single intervention bound enforced.",
            )
        if case.amount_paise <= 0:
            return StoppingRuleResult(
                should_stop=True,
                reason=f"Recovery case '{case.case_id}' has 0 amount due. No revenue at risk.",
            )

    # 3. Decision is NO_ACTION
    if action == RecoveryAction.NO_ACTION:
        return StoppingRuleResult(
            should_stop=True,
            reason="Decision Engine recommended NO_ACTION. No intervention required.",
        )

    return StoppingRuleResult(should_stop=False, reason=None)
