"""
Comprehensive test suite for Recovery Agent v0 (Milestone 4).
Tests deterministic orchestration, decision authority, action execution, failure handling,
idempotency, trace generation, anti-leakage, and API endpoints.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from agent.orchestrator import RecoveryAgent, recovery_agent
from agent.models import AgentRunStatus, StepType, StepStatus
from agent.errors import AgentIdempotencyConflictError, ActionMismatchError
from api.app import create_app
from api.services.recovery_service import recovery_service
from api.services.operations_service import operations_service
from recovery.repository import RecoveryRepository


@pytest.fixture(autouse=True)
def setup_services():
    test_repo = RecoveryRepository(db_path=":memory:")
    operations_service.repository = test_repo
    from analytics.service import analytics_service
    from analytics.repository import AnalyticsRepository
    analytics_service.repository = AnalyticsRepository(test_repo)

    model_path = Path("models/champion_recovery_model.pkl")
    recovery_service.load_model(model_path)


@pytest.fixture
def client(setup_services):
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_agent_end_to_end_orchestration():
    """Verify RecoveryAgent orchestrates case ingestion, decisioning, execution, and trace logging."""
    agent = RecoveryAgent()
    case_payload = {
        "case_id": "case_agent_001",
        "customer_id": "cust_agent_001",
        "amount_paise": 450000,
        "currency": "INR",
        "payment_method": "upi",
        "is_subscription": False,
        "customer_historical_success_rate": 0.94,
        "customer_total_transactions": 30,
        "customer_total_failures": 1,
        "customer_avg_amount_paise": 450000,
        "customer_tenure_months": 16,
        "failure_type": "temporary_failure",
        "retry_count": 0,
        "hours_since_failure": 0.2,
    }

    result = agent.run(case_payload, idempotency_key="idemp_agent_001_v1")

    assert result.status == "completed"
    assert result.case_id == "case_agent_001"
    assert result.decision_id is not None
    assert result.recommended_action == "retry"
    assert result.executed_action == "retry"
    assert result.execution_status == "EXECUTED"
    assert result.final_operational_state == "ACTION_EXECUTED"
    assert result.expected_net_paise == result.expected_gross_paise - result.action_cost_paise

    # Check trace
    trace = result.trace
    assert len(trace.steps) >= 3
    step_types = [s.step_type for s in trace.steps]
    assert StepType.CASE_RETRIEVED in step_types
    assert StepType.DECISION_OBTAINED in step_types
    assert StepType.ACTION_EXECUTED in step_types


def test_agent_technical_execution_failure_handling():
    """
    Verify that a technical execution failure is recorded as EXECUTION_FAILED
    and does NOT permit action substitution.
    """
    agent = RecoveryAgent()
    case_payload = {
        "case_id": "case_agent_002",
        "customer_id": "cust_agent_002",
        "amount_paise": 350000,
        "currency": "INR",
        "payment_method": "upi",
        "is_subscription": False,
        "failure_type": "temporary_failure",
        "retry_count": 0,
        "hours_since_failure": 0.3,
    }

    result = agent.run(
        case_payload,
        idempotency_key="idemp_agent_002_fail",
        force_failure=True,
    )

    assert result.execution_status == "FAILED"
    assert result.final_operational_state == "EXECUTION_FAILED"
    assert result.recommended_action == "retry"
    # Action substitution is prohibited even on failure
    assert result.executed_action == "retry"

    step_types = [s.step_type for s in result.trace.steps]
    assert StepType.ACTION_EXECUTED in step_types or StepType.ACTION_FAILED in step_types


def test_agent_idempotent_replay():
    """Verify submitting the same run with identical idempotency key returns cached result."""
    agent = RecoveryAgent()
    case_payload = {
        "case_id": "case_agent_003",
        "customer_id": "cust_agent_003",
        "amount_paise": 500000,
        "currency": "INR",
        "payment_method": "upi",
        "failure_type": "temporary_failure",
        "retry_count": 0,
    }

    idemp_key = "idemp_agent_003_unique"
    res1 = agent.run(case_payload, idempotency_key=idemp_key)
    res2 = agent.run(case_payload, idempotency_key=idemp_key)

    assert res1.agent_run_id == res2.agent_run_id
    assert res1.case_id == res2.case_id


def test_agent_idempotency_conflict_detection():
    """Verify reusing an existing idempotency key for a DIFFERENT case raises conflict error."""
    agent = RecoveryAgent()
    case1 = {"case_id": "case_agent_004a", "customer_id": "cust_a", "amount_paise": 100000}
    case2 = {"case_id": "case_agent_004b", "customer_id": "cust_b", "amount_paise": 200000}

    idemp_key = "idemp_shared_conflict_key"
    agent.run(case1, idempotency_key=idemp_key)

    with pytest.raises(AgentIdempotencyConflictError, match="cannot be reused for case"):
        agent.run(case2, idempotency_key=idemp_key)


def test_agent_get_run_trace_retrieval():
    """Verify agent run and complete trace can be retrieved from SQLite repository."""
    agent = RecoveryAgent()
    case_payload = {
        "case_id": "case_agent_005",
        "customer_id": "cust_agent_005",
        "amount_paise": 250000,
        "currency": "INR",
        "payment_method": "upi",
        "failure_type": "temporary_failure",
    }

    res = agent.run(case_payload, idempotency_key="idemp_agent_005_v1")
    retrieved = agent.get_run(res.agent_run_id)

    assert retrieved is not None
    assert retrieved.agent_run_id == res.agent_run_id
    assert retrieved.case_id == "case_agent_005"
    assert len(retrieved.trace.steps) == len(res.trace.steps)


def test_api_agent_recover_endpoint(client):
    """Verify POST /api/v1/agent/recover merchant API endpoint."""
    payload = {
        "case_id": "case_api_agent_001",
        "customer_id": "cust_api_agent_001",
        "amount_paise": 600000,
        "currency": "INR",
        "payment_method": "upi",
        "is_subscription": False,
        "customer_historical_success_rate": 0.92,
        "customer_total_transactions": 25,
        "customer_total_failures": 2,
        "customer_avg_amount_paise": 600000,
        "customer_tenure_months": 14,
        "failure_type": "temporary_failure",
        "retry_count": 0,
        "hours_since_failure": 0.2,
        "idempotency_key": "idemp_api_agent_001",
    }

    resp = client.post("/api/v1/agent/recover", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["case_id"] == "case_api_agent_001"
    assert data["recommended_action"] == "retry"
    assert data["executed_action"] == "retry"
    assert data["execution_status"] == "EXECUTED"
    assert "agent_run_id" in data
    assert "trace" in data

    # Retrieve run via GET /api/v1/agent/runs/{agent_run_id}
    run_id = data["agent_run_id"]
    get_resp = client.get(f"/api/v1/agent/runs/{run_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["agent_run_id"] == run_id


def test_api_agent_rejects_forbidden_ground_truth_fields(client):
    """ANTI-LEAKAGE: Verify API rejects any forbidden simulator latent/ground-truth parameters."""
    payload = {
        "case_id": "case_leak_001",
        "customer_id": "cust_leak_001",
        "amount_paise": 100000,
        "forbidden_latent_intent": 0.99,
    }
    resp = client.post("/api/v1/agent/recover", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_agent_handles_no_action_decision():
    """Verify that when no_action is chosen (e.g. negative EV micro ticket), agent executes no_action safely."""
    agent = RecoveryAgent()
    case_payload = {
        "case_id": "case_agent_no_act",
        "customer_id": "cust_agent_no_act",
        "amount_paise": 100,  # 1 INR -> negative EV for all interventions -> no_action
        "currency": "INR",
        "payment_method": "card",
        "failure_type": "temporary_failure",
        "retry_count": 3,
        "hours_since_failure": 24.0,
    }

    result = agent.run(case_payload, idempotency_key="idemp_no_act_001")
    assert result.status == "completed"
    assert result.recommended_action == "no_action"
    assert result.executed_action == "no_action"
    assert result.execution_status == "EXECUTED"
    assert result.action_cost_paise == 0


def test_agent_settles_outcome_via_orchestrator():
    """Verify agent can settle an outcome (e.g. webhook simulation) resulting in RECOVERED state."""
    agent = RecoveryAgent()
    case_payload = {
        "case_id": "case_agent_outcome",
        "customer_id": "cust_agent_outcome",
        "amount_paise": 800000,
        "currency": "INR",
        "payment_method": "upi",
        "failure_type": "temporary_failure",
        "retry_count": 0,
    }

    result = agent.run(
        case_payload,
        idempotency_key="idemp_outcome_001",
        outcome_status="recovered",
        recovered_amount_paise=800000,
    )
    assert result.status == "completed"
    assert result.execution_status == "EXECUTED"
    assert result.final_operational_state == "RECOVERED"
    assert result.outcome_status == "recovered"
    assert result.recovered_amount_paise == 800000


def test_agent_api_404_for_missing_run_id(client):
    """Verify GET /api/v1/agent/runs/{agent_run_id} returns 404 for non-existent run."""
    resp = client.get("/api/v1/agent/runs/run_nonexistent_12345")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_llm_compatible_agent_model_custom_driver():
    """
    Verify the pluggable AgentModel interface allows custom tool-calling drivers
    (foundational architecture for future Day 5 LLM agent integration).
    """
    from agent.runtime import AgentModel
    from agent.models import AgentContext
    from typing import Dict, Any, List, Optional

    class MockLLMToolDriver(AgentModel):
        """Mock LLM tool driver that issues explicit step-by-step tool decisions."""
        def __init__(self):
            self.step = 0

        def decide_next_tool(self, context: AgentContext, available_tools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            self.step += 1
            if self.step == 1:
                return {"tool": "get_recovery_decision", "arguments": {"case_id": context.case_id}}
            elif self.step == 2:
                return {
                    "tool": "execute_recovery_action",
                    "arguments": {
                        "decision_id": context.decision_id,
                        "action": context.recommended_action,
                        "idempotency_key": f"mock_llm_{context.case_id}",
                    },
                }
            return None

    driver = MockLLMToolDriver()
    agent = RecoveryAgent(agent_model=driver)

    case_payload = {
        "case_id": "case_mock_llm_001",
        "customer_id": "cust_mock_llm_001",
        "amount_paise": 750000,
        "currency": "INR",
        "payment_method": "upi",
        "failure_type": "temporary_failure",
    }

    res = agent.run(case_payload)
    assert res.status == "completed"
    assert res.decision_id is not None
    assert res.executed_action is not None
    assert res.execution_status == "EXECUTED"
    assert driver.step == 3
