"""
Unit tests for RecoverAI Subscription Domain Models, Billing-Cycle Identity, and Stopping Rules.
100% deterministic and offline.
"""

import pytest
from recovery.models import CaseState, RecoveryCaseRecord
from recovery.subscriptions.models import (
    RazorpaySubscriptionStatus,
    RecoveryResolutionSource,
    RecoverySource,
    SubscriptionRecord,
    derive_billing_cycle_case_id,
)
from recovery.subscriptions.stopping_rules import (
    StoppingRuleResult,
    evaluate_subscription_stopping_rules,
)
from simulator.config import RecoveryAction


def test_derive_billing_cycle_case_id_uniqueness():
    """Verify distinct billing cycles on same subscription produce distinct case IDs."""
    sub_id = "sub_abcdef123456"
    case_cycle_1 = derive_billing_cycle_case_id(sub_id, invoice_id="inv_001", cycle_index=1)
    case_cycle_2 = derive_billing_cycle_case_id(sub_id, invoice_id="inv_002", cycle_index=2)

    assert case_cycle_1 != case_cycle_2
    assert case_cycle_1.startswith("sub_")
    assert case_cycle_2.startswith("sub_")


def test_derive_billing_cycle_case_id_idempotency():
    """Verify identical inputs produce identical deterministic case IDs."""
    sub_id = "sub_abcdef123456"
    case_a = derive_billing_cycle_case_id(sub_id, invoice_id="inv_001", cycle_index=1)
    case_b = derive_billing_cycle_case_id(sub_id, invoice_id="inv_001", cycle_index=1)

    assert case_a == case_b


def test_subscription_record_schema():
    """Verify SubscriptionRecord validation and fields."""
    rec = SubscriptionRecord(
        subscription_id="sub_test_001",
        customer_id="cust_001",
        plan_id="plan_001",
        status=RazorpaySubscriptionStatus.ACTIVE,
        current_cycle=3,
        total_cycles=12,
        amount_due_paise=150000,
        currency="INR",
        charge_attempt_count=1,
    )
    assert rec.subscription_id == "sub_test_001"
    assert rec.status == RazorpaySubscriptionStatus.ACTIVE
    assert rec.amount_due_paise == 150000
    assert rec.charge_attempt_count == 1
    assert rec.is_recoverable is True


def test_stopping_rules_cancelled_subscription():
    """Stopping rule stops intervention if subscription is cancelled."""
    sub = SubscriptionRecord(
        subscription_id="sub_cancel_001",
        customer_id="cust_001",
        status=RazorpaySubscriptionStatus.CANCELLED,
    )
    res = evaluate_subscription_stopping_rules(
        subscription=sub,
        case=None,
        action=RecoveryAction.PAYMENT_LINK,
    )
    assert res.should_stop is True
    assert "cancelled" in str(res.reason).lower()


def test_stopping_rules_completed_subscription():
    """Stopping rule stops intervention if subscription is completed."""
    sub = SubscriptionRecord(
        subscription_id="sub_comp_001",
        customer_id="cust_001",
        status=RazorpaySubscriptionStatus.COMPLETED,
    )
    res = evaluate_subscription_stopping_rules(
        subscription=sub,
        case=None,
        action=RecoveryAction.PAYMENT_LINK,
    )
    assert res.should_stop is True
    assert "completed" in str(res.reason).lower()


def test_stopping_rules_terminal_case():
    """Stopping rule stops intervention if case is already settled as RECOVERED or NOT_RECOVERED."""
    sub = SubscriptionRecord(
        subscription_id="sub_001",
        customer_id="cust_001",
        status=RazorpaySubscriptionStatus.PENDING,
    )
    case_recovered = RecoveryCaseRecord(
        case_id="case_001",
        customer_id="cust_001",
        amount_paise=100000,
        current_state=CaseState.RECOVERED,
        decision_id="dec_001",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )
    res = evaluate_subscription_stopping_rules(
        subscription=sub,
        case=case_recovered,
        action=RecoveryAction.PAYMENT_LINK,
    )
    assert res.should_stop is True
    assert "terminal state" in str(res.reason).lower()


def test_stopping_rules_action_already_executed():
    """Stopping rule enforces single-intervention bound per cycle if ACTION_EXECUTED."""
    sub = SubscriptionRecord(
        subscription_id="sub_001",
        customer_id="cust_001",
        status=RazorpaySubscriptionStatus.PENDING,
    )
    case_executed = RecoveryCaseRecord(
        case_id="case_001",
        customer_id="cust_001",
        amount_paise=100000,
        current_state=CaseState.ACTION_EXECUTED,
        decision_id="dec_001",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        last_action_id="act_001",
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )
    res = evaluate_subscription_stopping_rules(
        subscription=sub,
        case=case_executed,
        action=RecoveryAction.PAYMENT_LINK,
    )
    assert res.should_stop is True
    assert "single intervention" in str(res.reason).lower()


def test_stopping_rules_no_action_decision():
    """Stopping rule stops when decision is NO_ACTION."""
    sub = SubscriptionRecord(
        subscription_id="sub_001",
        customer_id="cust_001",
        status=RazorpaySubscriptionStatus.PENDING,
    )
    res = evaluate_subscription_stopping_rules(
        subscription=sub,
        case=None,
        action=RecoveryAction.NO_ACTION,
    )
    assert res.should_stop is True
    assert "no_action" in str(res.reason).lower()


def test_stopping_rules_permitted_intervention():
    """Stopping rule permits intervention on active/pending subscription with no executed action."""
    sub = SubscriptionRecord(
        subscription_id="sub_001",
        customer_id="cust_001",
        status=RazorpaySubscriptionStatus.PENDING,
        amount_due_paise=299900,
    )
    case_decided = RecoveryCaseRecord(
        case_id="case_001",
        customer_id="cust_001",
        amount_paise=299900,
        current_state=CaseState.DECIDED,
        decision_id="dec_001",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )
    res = evaluate_subscription_stopping_rules(
        subscription=sub,
        case=case_decided,
        action=RecoveryAction.PAYMENT_LINK,
    )
    assert res.should_stop is False
    assert res.reason is None
