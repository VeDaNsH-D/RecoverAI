"""
Unit test suite for RecoverAI Agent Tools (Milestone 4).
Tests tool registration, schema contracts, decision delegation, action consistency, and safety boundaries.
"""

from pathlib import Path
import pytest

from agent.models import AgentContext
from agent.tools.registry import default_tool_registry, ToolRegistry
from agent.tools.case import GetPaymentCaseTool
from agent.tools.decision import GetRecoveryDecisionTool
from agent.tools.action import ExecuteRecoveryActionTool
from agent.tools.action_status import GetActionStatusTool
from agent.tools.outcome import RecordRecoveryOutcomeTool
from agent.tools.summary import GetRecoverySummaryTool
from agent.errors import ActionMismatchError, ToolExecutionError
from api.services.recovery_service import recovery_service
from api.services.operations_service import operations_service
from recovery.repository import RecoveryRepository


@pytest.fixture(autouse=True)
def setup_services():
    # Use isolated shared in-memory DB for tests
    test_repo = RecoveryRepository(db_path=":memory:")
    operations_service.repository = test_repo
    from analytics.service import analytics_service
    from analytics.repository import AnalyticsRepository
    analytics_service.repository = AnalyticsRepository(test_repo)

    # Load champion model
    model_path = Path("models/champion_recovery_model.pkl")
    recovery_service.load_model(model_path)


def test_tool_registry_initialization():
    """Verify tool registry pre-loads all approved recovery tools."""
    registry = ToolRegistry()
    tools = registry.list_tools()
    tool_names = [t["name"] for t in tools]

    expected = [
        "get_payment_case",
        "get_recovery_decision",
        "execute_recovery_action",
        "get_action_status",
        "record_recovery_outcome",
        "get_recovery_summary",
        "sync_razorpay_payment_link",
    ]
    assert sorted(tool_names) == sorted(expected)


def test_get_payment_case_tool():
    """Verify GetPaymentCaseTool populates observable context and rejects latent variables."""
    tool = GetPaymentCaseTool()
    ctx = AgentContext(
        case_id="case_tool_001",
        customer_id="cust_tool_001",
        amount_paise=500000,
        payment_method="upi",
        failure_type="temporary_failure",
    )

    out = tool.execute(ctx, case_id="case_tool_001")
    assert out["case_id"] == "case_tool_001"
    assert out["amount_paise"] == 500000
    assert out["amount_inr"] == 5000.0
    assert "latent_intent" not in out
    assert "ground_truth_probability" not in out


def test_get_recovery_decision_tool():
    """Verify GetRecoveryDecisionTool calls authoritative ML decision engine and updates context."""
    tool = GetRecoveryDecisionTool()
    ctx = AgentContext(
        case_id="case_tool_002",
        customer_id="cust_tool_002",
        amount_paise=300000,
        currency="INR",
        payment_method="upi",
        failure_type="temporary_failure",
        retry_count=0,
        hours_since_failure=0.2,
    )

    out = tool.execute(ctx)
    assert ctx.decision_id is not None
    assert ctx.recommended_action in ["retry", "payment_link", "reminder", "escalate", "no_action"]
    assert ctx.recovery_probability is not None
    assert ctx.expected_net_paise == ctx.expected_gross_paise - ctx.action_cost_paise
    assert out["expected_net_recovery_paise"] == ctx.expected_net_paise


def test_execute_recovery_action_tool_matching_action():
    """Verify ExecuteRecoveryActionTool executes when action matches recommendation."""
    dec_tool = GetRecoveryDecisionTool()
    act_tool = ExecuteRecoveryActionTool()

    ctx = AgentContext(
        case_id="case_tool_003",
        customer_id="cust_tool_003",
        amount_paise=400000,
        currency="INR",
        payment_method="upi",
        failure_type="temporary_failure",
        retry_count=0,
        hours_since_failure=0.2,
    )

    dec_tool.execute(ctx)
    assert ctx.decision_id is not None
    assert ctx.recommended_action is not None

    # Execute recommended action
    out = act_tool.execute(
        ctx,
        decision_id=ctx.decision_id,
        action=ctx.recommended_action,
        idempotency_key="idemp_tool_003_v1",
    )
    assert out["status"] == "EXECUTED"
    assert ctx.action_id == out["action_id"]
    assert ctx.current_operational_state == "ACTION_EXECUTED"


def test_execute_recovery_action_tool_action_mismatch_forbidden():
    """
    CRITICAL SAFETY TEST:
    Verify that an attempt to execute an action DIFFERENT from the decision recommendation is blocked!
    """
    dec_tool = GetRecoveryDecisionTool()
    act_tool = ExecuteRecoveryActionTool()

    ctx = AgentContext(
        case_id="case_tool_004",
        customer_id="cust_tool_004",
        amount_paise=200000,
        currency="INR",
        payment_method="upi",
        failure_type="temporary_failure",
        retry_count=0,
        hours_since_failure=0.2,
    )

    dec_tool.execute(ctx)
    assert ctx.decision_id is not None
    rec_act = ctx.recommended_action

    # Attempt to execute an unauthorized substitute action
    unauthorized_action = "escalate" if rec_act != "escalate" else "reminder"
    with pytest.raises(ActionMismatchError, match="Action substitution is strictly forbidden"):
        act_tool.execute(
            ctx,
            decision_id=ctx.decision_id,
            action=unauthorized_action,
            idempotency_key="idemp_tool_004_mismatch",
        )


def test_record_recovery_outcome_tool():
    """Verify RecordRecoveryOutcomeTool records terminal settlement and updates ledger."""
    dec_tool = GetRecoveryDecisionTool()
    act_tool = ExecuteRecoveryActionTool()
    out_tool = RecordRecoveryOutcomeTool()

    ctx = AgentContext(
        case_id="case_tool_005",
        customer_id="cust_tool_005",
        amount_paise=600000,
        currency="INR",
        payment_method="upi",
        failure_type="temporary_failure",
        retry_count=0,
        hours_since_failure=0.2,
    )

    dec_tool.execute(ctx)
    act_tool.execute(
        ctx,
        decision_id=ctx.decision_id,
        action=ctx.recommended_action,
        idempotency_key="idemp_tool_005_v1",
    )

    # Record recovered outcome
    out = out_tool.execute(
        ctx,
        case_id=ctx.case_id,
        action_id=ctx.action_id,
        decision_id=ctx.decision_id,
        outcome_status="recovered",
        recovered_amount_paise=600000,
    )
    assert out["outcome_status"] == "recovered"
    assert out["recovered_amount_paise"] == 600000
    assert ctx.current_operational_state == "RECOVERED"
