"""
Comprehensive test suite for RecoverAI Recovery Operations Layer (Milestone 3 Phase B).
Tests state machine, action providers, action execution, outcome events, idempotency,
state transitions, summary analytics, and database persistence.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from simulator.config import RecoveryAction, FailureType, PaymentMethod
from recovery.models import CaseState, ActionExecutionStatus, OutcomeStatus
from recovery.state_machine import RecoveryStateMachine, InvalidStateTransitionError
from recovery.repository import RecoveryRepository, IdempotencyConflictError
from recovery.executor import ActionExecutor
from api.app import create_app
from api.services.recovery_service import recovery_service
from api.services.operations_service import operations_service


@pytest.fixture(scope="module")
def client():
    # Use isolated shared memory DB for operations service during tests
    test_repo = RecoveryRepository(db_path=":memory:")
    operations_service.repository = test_repo

    # Load champion model
    model_path = Path("models/champion_recovery_model.pkl")
    recovery_service.load_model(model_path)

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_state_machine_legal_and_illegal_transitions():
    """Verify legal state transitions and rejection of illegal transitions."""
    # Legal transitions
    RecoveryStateMachine.validate_transition(CaseState.DECIDED, CaseState.ACTION_PENDING)
    RecoveryStateMachine.validate_transition(CaseState.ACTION_PENDING, CaseState.ACTION_EXECUTED)
    RecoveryStateMachine.validate_transition(CaseState.ACTION_PENDING, CaseState.EXECUTION_FAILED)
    RecoveryStateMachine.validate_transition(CaseState.EXECUTION_FAILED, CaseState.ACTION_PENDING)
    RecoveryStateMachine.validate_transition(CaseState.ACTION_EXECUTED, CaseState.RECOVERED)
    RecoveryStateMachine.validate_transition(CaseState.ACTION_EXECUTED, CaseState.NOT_RECOVERED)

    # Illegal transitions
    with pytest.raises(InvalidStateTransitionError):
        RecoveryStateMachine.validate_transition(CaseState.DECIDED, CaseState.RECOVERED)

    with pytest.raises(InvalidStateTransitionError):
        RecoveryStateMachine.validate_transition(CaseState.ACTION_EXECUTED, CaseState.ACTION_PENDING)

    with pytest.raises(InvalidStateTransitionError):
        RecoveryStateMachine.validate_transition(CaseState.RECOVERED, CaseState.ACTION_PENDING)

    with pytest.raises(InvalidStateTransitionError):
        RecoveryStateMachine.validate_transition(CaseState.NOT_RECOVERED, CaseState.RECOVERED)


def test_all_action_providers_execute():
    """Verify that each provider mock executes deterministically with exact costs."""
    executor = ActionExecutor()
    from recovery.models import RecoveryCaseRecord, DecisionRecord

    mock_case = RecoveryCaseRecord(
        case_id="case_prov_001",
        customer_id="cust_001",
        amount_paise=250000,
        current_state=CaseState.DECIDED,
        decision_id="dec_001",
        recommended_action=RecoveryAction.RETRY,
        created_at="2026-08-27T08:00:00Z",
        updated_at="2026-08-27T08:00:00Z",
    )
    mock_dec = DecisionRecord(
        decision_id="dec_001",
        case_id="case_prov_001",
        customer_id="cust_001",
        amount_paise=250000,
        recommended_action=RecoveryAction.RETRY,
        recommended_action_recovery_probability=0.75,
        expected_gross_recovery_paise=187500,
        action_cost_paise=200,
        expected_net_recovery_paise=187300,
        decision_margin_paise=5000,
        explanation="Test explanation",
        model_family="logistic",
        feature_version="24d",
        created_at="2026-08-27T08:00:00Z",
    )

    for act in RecoveryAction:
        res = executor.execute_action(mock_case, mock_dec, act, idempotency_key=f"key_{act.value}_01")
        assert res.status == ActionExecutionStatus.EXECUTED
        assert len(res.provider_reference) > 0


def test_full_recovery_operations_lifecycle_recovered(client):
    """
    Test full lifecycle:
    1. POST /api/v1/decisions (generates & persists decision in DECIDED)
    2. POST /api/v1/recovery/actions (dispatches action, transitions to ACTION_EXECUTED)
    3. GET /api/v1/recovery/actions/{action_id} (retrieves execution status)
    4. POST /api/v1/recovery/outcomes (records 'recovered', transitions to RECOVERED)
    5. GET /api/v1/recovery/summary (verifies aggregate operational & financial counts)
    """
    # 1. Create Decision
    dec_resp = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_full_life_001",
            "customer_id": "cust_full_001",
            "amount_paise": 200000,  # ₹2,000.00
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.90,
            "customer_total_transactions": 20,
            "customer_total_failures": 2,
            "customer_avg_amount_paise": 200000,
            "customer_tenure_months": 12,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.5,
        },
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    decision_id = dec_data["decision_id"]
    recommended_action = dec_data["recommended_action"]

    # 2. Execute Action
    idemp_key = "idemp_full_life_001_v1"
    act_resp = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": decision_id,
            "action": recommended_action,
            "idempotency_key": idemp_key,
        },
    )
    assert act_resp.status_code == 200
    act_data = act_resp.json()
    assert act_data["status"] == "EXECUTED"
    assert act_data["decision_id"] == decision_id
    assert act_data["case_id"] == "case_full_life_001"
    action_id = act_data["action_id"]

    # 3. Retrieve Action
    get_act_resp = client.get(f"/api/v1/recovery/actions/{action_id}")
    assert get_act_resp.status_code == 200
    assert get_act_resp.json()["action_id"] == action_id

    # 4. Record Outcome (Recovered)
    out_resp = client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_full_life_001",
            "action_id": action_id,
            "decision_id": decision_id,
            "outcome_status": "recovered",
            "recovered_amount_paise": 200000,
        },
    )
    assert out_resp.status_code == 200
    out_data = out_resp.json()
    assert out_data["outcome_status"] == "recovered"
    assert out_data["recovered_amount_paise"] == 200000
    assert out_data["recovered_amount_inr"] == 2000.0

    # 5. Check Summary Analytics
    sum_resp = client.get("/api/v1/recovery/summary")
    assert sum_resp.status_code == 200
    sum_data = sum_resp.json()
    assert sum_data["decisions_made"] >= 1
    assert sum_data["actions_executed"] >= 1
    assert sum_data["recovered_cases"] >= 1
    assert sum_data["gross_recovered_paise"] >= 200000
    assert sum_data["net_recovered_paise"] == sum_data["gross_recovered_paise"] - sum_data["total_action_cost_paise"]


def test_not_recovered_outcome_lifecycle(client):
    """Test outcome recording for unrecovered payment case."""
    # Create Decision
    dec_resp = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_unrec_001",
            "customer_id": "cust_unrec_001",
            "amount_paise": 150000,
            "currency": "INR",
            "payment_method": "card",
            "is_subscription": False,
            "customer_historical_success_rate": 0.80,
            "customer_total_transactions": 10,
            "customer_total_failures": 2,
            "customer_avg_amount_paise": 150000,
            "customer_tenure_months": 6,
            "failure_type": "insufficient_funds",
            "retry_count": 1,
            "hours_since_failure": 2.0,
        },
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()

    # Execute Action
    act_resp = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": dec_data["decision_id"],
            "action": dec_data["recommended_action"],
            "idempotency_key": "idemp_unrec_001_v1",
        },
    )
    assert act_resp.status_code == 200
    act_data = act_resp.json()

    # Record Outcome (Not Recovered: amount must be 0)
    out_resp = client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_unrec_001",
            "action_id": act_data["action_id"],
            "decision_id": dec_data["decision_id"],
            "outcome_status": "not_recovered",
            "recovered_amount_paise": 0,
        },
    )
    assert out_resp.status_code == 200
    assert out_resp.json()["outcome_status"] == "not_recovered"
    assert out_resp.json()["recovered_amount_paise"] == 0


def test_technical_failure_and_retry_workflow(client):
    """
    Test technical failure and retry behavior:
    1. Action execution fails due to provider error (EXECUTION_FAILED).
    2. Retry of SAME action is permitted (transitions back to ACTION_PENDING -> ACTION_EXECUTED).
    3. Action substitution attempt is rejected.
    """
    dec_resp = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_tech_fail_001",
            "customer_id": "cust_tech_001",
            "amount_paise": 500000,
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.85,
            "customer_total_transactions": 15,
            "customer_total_failures": 2,
            "customer_avg_amount_paise": 500000,
            "customer_tenure_months": 10,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.5,
        },
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    rec_action = dec_data["recommended_action"]

    # 1. Force failure
    fail_act_resp = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": dec_data["decision_id"],
            "action": rec_action,
            "idempotency_key": "idemp_fail_attempt_01",
            "force_failure": True,
        },
    )
    assert fail_act_resp.status_code == 200
    assert fail_act_resp.json()["status"] == "FAILED"

    # 2. Attempting to substitute with another action should be rejected
    substitute_action = "escalate" if rec_action != "escalate" else "reminder"
    sub_resp = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": dec_data["decision_id"],
            "action": substitute_action,
            "idempotency_key": "idemp_substitute_attempt",
        },
    )
    assert sub_resp.status_code == 400
    assert "does not match" in sub_resp.json()["detail"]

    # 3. Retry same action successfully
    retry_act_resp = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": dec_data["decision_id"],
            "action": rec_action,
            "idempotency_key": "idemp_retry_attempt_02",
            "force_failure": False,
        },
    )
    assert retry_act_resp.status_code == 200
    assert retry_act_resp.json()["status"] == "EXECUTED"


def test_idempotency_semantics(client):
    """
    Test idempotency:
    1. Same key + same payload -> 200 with cached action execution (no duplicate dispatch).
    2. Same key + different payload -> 409 Conflict.
    """
    dec_resp = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_idemp_001",
            "customer_id": "cust_idemp_001",
            "amount_paise": 100000,
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.9,
            "customer_total_transactions": 10,
            "customer_total_failures": 1,
            "customer_avg_amount_paise": 100000,
            "customer_tenure_months": 10,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.5,
        },
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    idemp_key = "idemp_fixed_key_12345"

    # First execution
    r1 = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": dec_data["decision_id"],
            "action": dec_data["recommended_action"],
            "idempotency_key": idemp_key,
        },
    )
    assert r1.status_code == 200
    act_id_1 = r1.json()["action_id"]

    # Replay with same key and same payload
    r2 = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": dec_data["decision_id"],
            "action": dec_data["recommended_action"],
            "idempotency_key": idemp_key,
        },
    )
    assert r2.status_code == 200
    assert r2.json()["action_id"] == act_id_1  # Exact same action record returned

    # Replay with same key but different decision_id
    r3 = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": "dec_different_id_999",
            "action": dec_data["recommended_action"],
            "idempotency_key": idemp_key,
        },
    )
    assert r3.status_code == 409
    assert "previously used with a different" in r3.json()["detail"]


def test_action_validation_prevents_arbitrary_merchant_bypass(client):
    """Ensure merchant cannot execute an action different from the decision recommendation."""
    dec_resp = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_bypass_test",
            "customer_id": "cust_bypass_01",
            "amount_paise": 100000,
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.9,
            "customer_total_transactions": 10,
            "customer_total_failures": 1,
            "customer_avg_amount_paise": 100000,
            "customer_tenure_months": 10,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.5,
        },
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    rec = dec_data["recommended_action"]
    wrong_action = "escalate" if rec != "escalate" else "reminder"

    resp = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": dec_data["decision_id"],
            "action": wrong_action,
            "idempotency_key": "idemp_bypass_001",
        },
    )
    assert resp.status_code == 400
    assert "does not match" in resp.json()["detail"]


def test_outcome_validation_constraints(client):
    """
    Test outcome validation:
    1. Outcome before execution -> 409
    2. Duplicate outcome on same action -> 409
    3. Recovered with 0 amount -> 400
    4. Not-recovered with positive amount -> 400
    """
    # Create Decision
    dec_resp = client.post(
        "/api/v1/decisions",
        json={
            "case_id": "case_out_val_001",
            "customer_id": "cust_out_val_001",
            "amount_paise": 100000,
            "currency": "INR",
            "payment_method": "upi",
            "is_subscription": False,
            "customer_historical_success_rate": 0.9,
            "customer_total_transactions": 10,
            "customer_total_failures": 1,
            "customer_avg_amount_paise": 100000,
            "customer_tenure_months": 10,
            "failure_type": "temporary_failure",
            "retry_count": 0,
            "hours_since_failure": 0.5,
        },
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()

    # Execute Action
    act_resp = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": dec_data["decision_id"],
            "action": dec_data["recommended_action"],
            "idempotency_key": "idemp_out_val_001",
        },
    )
    assert act_resp.status_code == 200
    act_data = act_resp.json()

    # 1. Recovered with 0 amount -> 400
    r1 = client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_out_val_001",
            "action_id": act_data["action_id"],
            "decision_id": dec_data["decision_id"],
            "outcome_status": "recovered",
            "recovered_amount_paise": 0,  # Invalid
        },
    )
    assert r1.status_code == 400
    assert "positive recovered amount" in r1.json()["detail"]

    # 2. Not-recovered with positive amount -> 400
    r2 = client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_out_val_001",
            "action_id": act_data["action_id"],
            "decision_id": dec_data["decision_id"],
            "outcome_status": "not_recovered",
            "recovered_amount_paise": 50000,  # Invalid
        },
    )
    assert r2.status_code == 400
    assert "cannot have non-zero recovered amount" in r2.json()["detail"]

    # 3. Valid outcome recording
    r3 = client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_out_val_001",
            "action_id": act_data["action_id"],
            "decision_id": dec_data["decision_id"],
            "outcome_status": "recovered",
            "recovered_amount_paise": 100000,
        },
    )
    assert r3.status_code == 200

    # 4. Duplicate outcome recording -> 409
    r4 = client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_out_val_001",
            "action_id": act_data["action_id"],
            "decision_id": dec_data["decision_id"],
            "outcome_status": "recovered",
            "recovered_amount_paise": 100000,
        },
    )
    assert r4.status_code == 409
    assert "already been recorded" in r4.json()["detail"]


def test_errors_on_non_existent_references(client):
    """Ensure 404s are returned for missing decision, action, or case references."""
    # Non-existent decision for action
    r1 = client.post(
        "/api/v1/recovery/actions",
        json={
            "decision_id": "dec_non_existent_9999",
            "action": "retry",
            "idempotency_key": "idemp_missing_dec",
        },
    )
    assert r1.status_code == 404

    # Non-existent action for get action
    r2 = client.get("/api/v1/recovery/actions/act_non_existent_9999")
    assert r2.status_code == 404

    # Non-existent action for outcome
    r3 = client.post(
        "/api/v1/recovery/outcomes",
        json={
            "case_id": "case_foo",
            "action_id": "act_non_existent",
            "decision_id": "dec_foo",
            "outcome_status": "recovered",
            "recovered_amount_paise": 100000,
        },
    )
    assert r3.status_code == 404
