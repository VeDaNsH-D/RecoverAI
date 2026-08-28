"""
Integration and unit tests for RazorpayPaymentLinkProvider adapter with ActionExecutor and OperationsService.
100% offline & deterministic via mocked client transport.
"""

from unittest.mock import MagicMock
import pytest

from api.schemas import ActionExecutionRequest
from api.services.operations_service import OperationsService
from recovery.actions.base import ActionExecutionStatus
from recovery.models import (
    CaseState,
    DecisionRecord,
    RecoveryAction,
    RecoveryCaseRecord,
)
from recovery.providers.razorpay.client import RazorpayClient
from recovery.providers.razorpay.payment_link import RazorpayPaymentLinkProvider
from recovery.providers.razorpay.schemas import RazorpayPaymentLinkResponse
from recovery.repository import RecoveryRepository


@pytest.fixture
def mock_client():
    client = RazorpayClient(key_id="rzp_test_fixture123", key_secret="secret_fixture456")
    return client


def test_razorpay_payment_link_provider_success(mock_client):
    """Verify RazorpayPaymentLinkProvider executes successfully and returns EXECUTED with 1000 paise cost."""
    provider = RazorpayPaymentLinkProvider(client=mock_client)

    case = RecoveryCaseRecord(
        case_id="case_plink_001",
        customer_id="cust_001",
        amount_paise=650000,
        current_state=CaseState.ACTION_PENDING,
        decision_id="dec_001",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        created_at="2026-08-28T12:00:00Z",
        updated_at="2026-08-28T12:00:00Z",
    )

    decision = DecisionRecord(
        decision_id="dec_001",
        case_id="case_plink_001",
        customer_id="cust_001",
        amount_paise=650000,
        recommended_action=RecoveryAction.PAYMENT_LINK,
        recommended_action_recovery_probability=0.75,
        expected_gross_recovery_paise=487500,
        action_cost_paise=1000,
        expected_net_recovery_paise=486500,
        decision_margin_paise=100000,
        explanation="Test explanation",
        model_family="logistic_regression",
        feature_version="v1.0",
        created_at="2026-08-28T12:00:00Z",
    )

    mock_resp = RazorpayPaymentLinkResponse(
        id="plink_TEST_123456",
        short_url="https://rzp.io/i/TestLink123",
        status="created",
        amount=650000,
        amount_paid=0,
        currency="INR",
        reference_id="rec_case_plink_001_idemp_001",
    )
    mock_client.create_payment_link = MagicMock(return_value=mock_resp)

    res = provider.execute(case=case, decision=decision, idempotency_key="idemp_001")

    assert res.status == ActionExecutionStatus.EXECUTED
    assert res.provider_reference == "plink_TEST_123456"
    assert res.cost_paise == 1000
    assert res.metadata["short_url"] == "https://rzp.io/i/TestLink123"
    assert res.metadata["provider"] == "razorpay_test"


def test_razorpay_payment_link_provider_rejects_micro_amount(mock_client):
    """Verify amounts below 100 paise are rejected with FAILED and 0 cost."""
    provider = RazorpayPaymentLinkProvider(client=mock_client)

    case = RecoveryCaseRecord(
        case_id="case_plink_micro",
        customer_id="cust_001",
        amount_paise=50,  # 50 paise < 100 paise minimum
        current_state=CaseState.ACTION_PENDING,
        decision_id="dec_001",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        created_at="2026-08-28T12:00:00Z",
        updated_at="2026-08-28T12:00:00Z",
    )

    decision = DecisionRecord(
        decision_id="dec_001",
        case_id="case_plink_micro",
        customer_id="cust_001",
        amount_paise=50,
        recommended_action=RecoveryAction.PAYMENT_LINK,
        recommended_action_recovery_probability=0.5,
        expected_gross_recovery_paise=25,
        action_cost_paise=1000,
        expected_net_recovery_paise=0,
        decision_margin_paise=0,
        explanation="Micro amount",
        model_family="logistic_regression",
        feature_version="v1.0",
        created_at="2026-08-28T12:00:00Z",
    )

    res = provider.execute(case=case, decision=decision, idempotency_key="idemp_micro")

    assert res.status == ActionExecutionStatus.FAILED
    assert res.cost_paise == 0
    assert "below Razorpay minimum transaction threshold" in (res.error_message or "")


def test_razorpay_payment_link_provider_technical_failure_handling(mock_client):
    """Verify gateway exceptions return FAILED, 0 cost, and sanitized error message."""
    provider = RazorpayPaymentLinkProvider(client=mock_client)
    mock_client.create_payment_link = MagicMock(side_effect=RuntimeError("Gateway connection timed out"))

    case = RecoveryCaseRecord(
        case_id="case_plink_fail",
        customer_id="cust_001",
        amount_paise=500000,
        current_state=CaseState.ACTION_PENDING,
        decision_id="dec_001",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        created_at="2026-08-28T12:00:00Z",
        updated_at="2026-08-28T12:00:00Z",
    )

    decision = DecisionRecord(
        decision_id="dec_001",
        case_id="case_plink_fail",
        customer_id="cust_001",
        amount_paise=500000,
        recommended_action=RecoveryAction.PAYMENT_LINK,
        recommended_action_recovery_probability=0.75,
        expected_gross_recovery_paise=375000,
        action_cost_paise=1000,
        expected_net_recovery_paise=374000,
        decision_margin_paise=100000,
        explanation="Test",
        model_family="logistic_regression",
        feature_version="v1.0",
        created_at="2026-08-28T12:00:00Z",
    )

    res = provider.execute(case=case, decision=decision, idempotency_key="idemp_fail")

    assert res.status == ActionExecutionStatus.FAILED
    assert res.cost_paise == 0
    assert "connection timed out" in (res.error_message or "")


def test_operations_service_full_razorpay_lifecycle(mock_client):
    """Verify OperationsService dispatches to Razorpay provider and persists provider_reference."""
    repo = RecoveryRepository(db_path=":memory:")
    op_service = OperationsService(repository=repo)

    # Register Razorpay provider in executor
    razorpay_prov = RazorpayPaymentLinkProvider(client=mock_client)
    op_service.executor.register_provider(RecoveryAction.PAYMENT_LINK, razorpay_prov)

    # 1. Mock decision
    mock_resp = RazorpayPaymentLinkResponse(
        id="plink_LIFECYCLE_999",
        short_url="https://rzp.io/i/Lifecycle999",
        status="created",
        amount=700000,
        amount_paid=0,
        currency="INR",
        reference_id="rec_case_ops_001_idemp_ops_001",
    )
    mock_client.create_payment_link = MagicMock(return_value=mock_resp)

    # Persist case and decision
    case_rec = RecoveryCaseRecord(
        case_id="case_ops_001",
        customer_id="cust_ops_001",
        amount_paise=700000,
        current_state=CaseState.DECIDED,
        decision_id="dec_ops_001",
        recommended_action=RecoveryAction.PAYMENT_LINK,
        created_at="2026-08-28T12:00:00Z",
        updated_at="2026-08-28T12:00:00Z",
    )
    dec_rec = DecisionRecord(
        decision_id="dec_ops_001",
        case_id="case_ops_001",
        customer_id="cust_ops_001",
        amount_paise=700000,
        recommended_action=RecoveryAction.PAYMENT_LINK,
        recommended_action_recovery_probability=0.8,
        expected_gross_recovery_paise=560000,
        action_cost_paise=1000,
        expected_net_recovery_paise=559000,
        decision_margin_paise=200000,
        explanation="Optimal payment link",
        model_family="logistic_regression",
        feature_version="v1.0",
        created_at="2026-08-28T12:00:00Z",
    )
    repo.save_decision(dec_rec)

    # Execute action
    req = ActionExecutionRequest(
        decision_id="dec_ops_001",
        action=RecoveryAction.PAYMENT_LINK,
        idempotency_key="idemp_ops_001",
    )
    act_resp = op_service.execute_action(req)

    assert act_resp.status == ActionExecutionStatus.EXECUTED
    assert act_resp.provider_reference == "plink_LIFECYCLE_999"
    assert act_resp.cost_paise == 1000
    assert act_resp.cost_inr == 10.00

    # Verify lookup by provider reference
    retrieved_action = repo.get_action_by_provider_reference("plink_LIFECYCLE_999")
    assert retrieved_action is not None
    assert retrieved_action.action_id == act_resp.action_id
    assert retrieved_action.case_id == "case_ops_001"
