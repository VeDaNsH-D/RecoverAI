"""
Tests for RecoverAIInferenceEngine, human-readable explanations, and production inference isolation.
"""

from pathlib import Path
import pytest
import numpy as np
from pydantic import BaseModel

from simulator.config import FailureType, PaymentMethod, RecoveryAction
from simulator.schemas.case import PaymentCase
from ml.features import DataLeakageError
from ml.dataset import load_split_dataset_bundle
from ml.models.bundle import create_multi_action_model
from ml.decision_engine import DecisionResult
from ml.inference import RecoverAIInferenceEngine
from scripts.demo import create_demo_scenarios


@pytest.fixture(scope="module")
def inference_engine():
    data_dir = Path("data/sim_v1")
    if not data_dir.exists():
        pytest.skip("data/sim_v1 not found")
    train_bundle = load_split_dataset_bundle(data_dir, split="train")
    champion_model = create_multi_action_model("logistic", calibrate=True, random_state=42).fit_all(train_bundle)
    return RecoverAIInferenceEngine(model=champion_model)


def test_inference_engine_predict_and_explain(inference_engine):
    case = PaymentCase(
        case_id="case_inf_001",
        customer_id="cust_inf_001",
        merchant_id="merch_test",
        amount_paise=250000,  # ₹2,500
        currency="INR",
        payment_method=PaymentMethod.UPI,
        is_subscription=False,
        customer_historical_success_rate=0.90,
        customer_total_transactions=30,
        customer_total_failures=2,
        customer_avg_amount_paise=200000,
        customer_tenure_months=12,
        failure_type=FailureType.TEMPORARY_FAILURE,
        retry_count=0,
        hours_since_failure=0.5,
        created_at="2026-08-27T08:00:00Z",
    )

    dec = inference_engine.predict_decision(case)
    assert isinstance(dec, DecisionResult)
    assert dec.case_id == "case_inf_001"
    assert dec.selected_action in RecoveryAction
    assert dec.selected_expected_net_paise > 0

    explanation = inference_engine.explain_decision(case, dec)
    assert "RECOVERAI AUDITABLE DECISION REPORT" in explanation
    assert "RECOMMENDED ACTION" in explanation
    assert "ACTION ECONOMICS & SAFETY AUDIT LEDGER" in explanation
    assert "INR 2,500.00" in explanation

    d_dict = inference_engine.to_dict(case)
    assert d_dict["case_id"] == "case_inf_001"
    assert "action_evaluations" in d_dict
    assert len(d_dict["action_evaluations"]) == 5


def test_inference_boundary_anti_leakage(inference_engine):
    """Ensure that injecting forbidden ground-truth fields raises DataLeakageError."""
    class CorruptedCase(BaseModel):
        case_id: str = "case_bad"
        customer_id: str = "cust_bad"
        merchant_id: str = "merch_bad"
        amount_paise: int = 100000
        currency: str = "INR"
        payment_method: PaymentMethod = PaymentMethod.UPI
        is_subscription: bool = False
        customer_historical_success_rate: float = 0.9
        customer_total_transactions: int = 10
        customer_total_failures: int = 1
        customer_avg_amount_paise: int = 100000
        customer_tenure_months: int = 10
        failure_type: FailureType = FailureType.TEMPORARY_FAILURE
        retry_count: int = 0
        hours_since_failure: float = 1.0
        created_at: str = "2026-08-27T08:00:00Z"
        optimal_action: str = "retry"  # Injected forbidden key

    corrupted = CorruptedCase()
    with pytest.raises(DataLeakageError):
        inference_engine.predict_decision(corrupted)


def test_demo_scenarios_execution(inference_engine):
    scenarios = create_demo_scenarios()
    assert len(scenarios) == 8

    for title, case in scenarios:
        dec = inference_engine.predict_decision(case)
        assert dec.selected_action in RecoveryAction
        explanation = inference_engine.explain_decision(case, dec)
        assert len(explanation) > 100


def test_representative_safety_guardrails(inference_engine):
    scenarios = dict(create_demo_scenarios())

    # Scenario 2: retry_count = 2 must disqualify retry
    case_retry_exhausted = scenarios["Scenario 2: Exhausted Retries (Safety Guardrail Triggered: retry_count >= 2)"]
    dec_2 = inference_engine.predict_decision(case_retry_exhausted)
    assert dec_2.action_values[RecoveryAction.RETRY].allowed is False
    assert dec_2.selected_action != RecoveryAction.RETRY

    # Scenario 6: micro-ticket amount < ₹200 must disqualify escalate
    case_micro = scenarios["Scenario 6: Micro-Ticket Transaction (Guardrail: Escalate Suppressed for < INR 200)"]
    dec_6 = inference_engine.predict_decision(case_micro)
    assert dec_6.action_values[RecoveryAction.ESCALATE].allowed is False
    assert dec_6.selected_action != RecoveryAction.ESCALATE

    # Scenario 7: micro-ticket with negative intervention EVs must fall back safely to NO_ACTION
    case_neg = scenarios["Scenario 7: Micro-Ticket with Negative Intervention EV (Safe NO_ACTION Fallback)"]
    dec_7 = inference_engine.predict_decision(case_neg)
    assert dec_7.selected_action == RecoveryAction.NO_ACTION
