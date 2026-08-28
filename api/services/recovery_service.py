"""
Recovery Decision Service for RecoverAI API.
Orchestrates request validation, domain object creation, inference invocation, and response serialization.
GUARANTEE: Uses the existing authoritative RecoveryDecisionEngine without duplicating calculation logic.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import uuid

from simulator.config import RecoveryAction
from simulator.schemas.case import PaymentCase
from ml.inference import RecoverAIInferenceEngine
from ml.models.bundle import ACTION_ORDER
from api.schemas import (
    PaymentCaseRequest,
    DecisionResponse,
    CandidateActionResponse,
    SafetyStatusResponse,
    ModelInfoResponse,
)
from api.services.explanation_service import ExplanationService


class RecoveryService:
    """
    Singleton service wrapper around the RecoverAI ML Inference Engine.
    """

    def __init__(self, model_path: Optional[Path] = None):
        self._model_path = model_path
        self._engine: Optional[RecoverAIInferenceEngine] = None
        if model_path is not None:
            self.load_model(model_path)

    def load_model(self, model_path: Path) -> bool:
        """
        Loads the pre-trained champion model artifact into the inference engine.
        """
        path = Path(model_path)
        if not path.exists():
            self._engine = None
            return False

        try:
            self._engine = RecoverAIInferenceEngine(model_path=path)
            self._model_path = path
            return self._engine.is_ready
        except Exception:
            self._engine = None
            return False

    @property
    def is_ready(self) -> bool:
        """Returns True if the underlying inference engine is loaded and operational."""
        return self._engine is not None and self._engine.is_ready

    @property
    def model_family(self) -> str:
        return "calibrated_logistic_regression"

    def process_decision(self, request: PaymentCaseRequest) -> DecisionResponse:
        """
        Processes an observable payment case request and returns an auditable decision response.
        """
        if not self.is_ready or self._engine is None:
            raise RuntimeError("Recovery decision model is unavailable or not loaded.")

        # 1. Convert request into domain PaymentCase (separating metadata from ML observables)
        case = request.to_payment_case()

        # 2. Invoke authoritative RecoverAI inference & decision engine
        decision = self._engine.predict_decision(case)

        # 3. Generate merchant-friendly explanation
        explanation = ExplanationService.generate_merchant_explanation(case, decision)

        # 4. Assemble candidate actions ledger
        candidate_actions: List[CandidateActionResponse] = []
        for act in ACTION_ORDER:
            av = decision.action_values[act]
            candidate_actions.append(
                CandidateActionResponse(
                    action=av.action,
                    recovery_probability=av.predicted_probability,
                    expected_gross_recovery_paise=av.expected_gross_paise,
                    expected_gross_recovery_inr=av.expected_gross_inr,
                    action_cost_paise=av.action_cost_paise,
                    action_cost_inr=av.action_cost_inr,
                    expected_net_recovery_paise=av.expected_net_paise,
                    expected_net_recovery_inr=av.expected_net_inr,
                    allowed=av.allowed,
                    disqualification_reason=av.disqualification_reason,
                )
            )

        # 5. Build safety status report
        guardrails = ["no_action_always_available"]
        retry_disq = case.retry_count >= 2
        escalate_disq = case.amount_paise < 20000

        if retry_disq:
            guardrails.append("max_retries_exceeded")
        if escalate_disq:
            guardrails.append("micro_ticket_protection")

        safety_status = SafetyStatusResponse(
            guardrails_applied=guardrails,
            retry_disqualified=retry_disq,
            escalate_disqualified=escalate_disq,
        )

        sel_val = decision.action_values[decision.selected_action]
        decision_id = f"dec_{uuid.uuid4().hex[:12]}"
        now_ts = datetime.now(timezone.utc).isoformat()

        # 6. Persist historical decision record and initialize case in DECIDED state
        from api.services.operations_service import operations_service
        operations_service.persist_decision(
            decision_id=decision_id,
            case_id=case.case_id,
            customer_id=case.customer_id,
            amount_paise=case.amount_paise,
            recommended_action=decision.selected_action,
            recommended_action_recovery_probability=sel_val.predicted_probability,
            expected_gross_recovery_paise=sel_val.expected_gross_paise,
            action_cost_paise=sel_val.action_cost_paise,
            expected_net_recovery_paise=sel_val.expected_net_paise,
            decision_margin_paise=decision.decision_margin_paise,
            explanation=explanation,
            model_family=self.model_family,
            feature_version="sim_v1_canonical_24d",
            payment_method=case.payment_method.value if hasattr(case.payment_method, "value") else str(case.payment_method),
            is_subscription=bool(case.is_subscription),
            failure_type=case.failure_type.value if hasattr(case.failure_type, "value") else str(case.failure_type),
            retry_count=int(case.retry_count),
            created_at=now_ts,
        )

        return DecisionResponse(
            decision_id=decision_id,
            case_id=case.case_id,
            recommended_action=decision.selected_action,
            recommended_action_recovery_probability=sel_val.predicted_probability,
            expected_gross_recovery_paise=sel_val.expected_gross_paise,
            expected_gross_recovery_inr=sel_val.expected_gross_inr,
            action_cost_paise=sel_val.action_cost_paise,
            action_cost_inr=sel_val.action_cost_inr,
            expected_net_recovery_paise=sel_val.expected_net_paise,
            expected_net_recovery_inr=sel_val.expected_net_inr,
            decision_margin_paise=decision.decision_margin_paise,
            decision_margin_inr=decision.decision_margin_inr,
            explanation=explanation,
            safety_status=safety_status,
            candidate_actions=candidate_actions,
            timestamp=now_ts,
        )

    def get_model_info(self) -> ModelInfoResponse:
        """
        Returns safe, product-oriented model metadata.
        """
        return ModelInfoResponse(
            model_family=self.model_family,
            feature_version="sim_v1_canonical_24d",
            simulator_version="sim_v1",
            supported_actions=list(ACTION_ORDER),
            feature_count=24,
            active_safety_guardrails=[
                "no_action_always_available",
                "max_retry_suppression (retry_count >= 2)",
                "micro_ticket_escalate_suppression (amount < INR 200)",
            ],
            training_status="trained_and_frozen" if self.is_ready else "model_unavailable",
            disclaimer="Inference operates strictly on observable payment context with zero access to unobservable customer parameters.",
        )


# Global service instance
recovery_service = RecoveryService()
