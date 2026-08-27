"""
Expected Net Value Decision Engine & Safety Policy Layer for RecoverAI.
Transforms calibrated recovery probabilities into economically optimal bounded recovery interventions.
All monetary arithmetic is strictly computed in integer paise.
"""

import math
from typing import Dict, List, Optional
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from simulator.schemas.case import PaymentCase
from ml.features import FeatureExtractor
from ml.models.bundle import MultiActionRecoveryModel, ACTION_ORDER


# Thresholds & Safety Limits
MAX_RETRY_COUNT_ALLOWED = 2           # Disqualify RETRY if retry_count >= 2
MIN_AMOUNT_PAISE_FOR_ESCALATE = 20000  # Disqualify ESCALATE if amount < ₹200 (20,000 paise)


class ActionValue(BaseModel):
    """
    Detailed economic evaluation and safety audit for a single candidate recovery action.
    GUARANTEE: Uses exact integer paise monetary values.
    """
    model_config = ConfigDict(frozen=True)

    action: RecoveryAction = Field(description="Candidate recovery action")
    predicted_probability: float = Field(ge=0.0, le=1.0, description="Estimated recovery probability P(Y(a)=1 | X)")
    amount_paise: int = Field(ge=0, description="Total case transaction value in integer paise")
    expected_gross_paise: int = Field(ge=0, description="floor(predicted_probability * amount_paise)")
    action_cost_paise: int = Field(ge=0, description="Operational friction cost in paise")
    expected_net_paise: int = Field(description="expected_gross_paise - action_cost_paise")
    allowed: bool = Field(default=True, description="Whether action satisfies safety policy constraints")
    disqualification_reason: Optional[str] = Field(default=None, description="Policy reason if disqualified")

    @property
    def expected_gross_inr(self) -> float:
        return self.expected_gross_paise / 100.0

    @property
    def action_cost_inr(self) -> float:
        return self.action_cost_paise / 100.0

    @property
    def expected_net_inr(self) -> float:
        return self.expected_net_paise / 100.0


class DecisionResult(BaseModel):
    """
    Audit record of the decision engine output for a payment case.
    """
    model_config = ConfigDict(frozen=True)

    case_id: Optional[str] = Field(default=None, description="Identifier of the case evaluated")
    selected_action: RecoveryAction = Field(description="Action selected by expected value optimization")
    selected_expected_net_paise: int = Field(description="Expected net recovery of chosen action in paise")
    decision_margin_paise: int = Field(ge=0, description="Expected net gain over second-best allowed action")
    action_values: Dict[RecoveryAction, ActionValue] = Field(description="Full audit ledger of all candidate actions")

    @property
    def selected_expected_net_inr(self) -> float:
        return self.selected_expected_net_paise / 100.0

    @property
    def decision_margin_inr(self) -> float:
        return self.decision_margin_paise / 100.0


class RecoveryDecisionEngine:
    """
    Evaluates observable PaymentCase instances, computes expected net recovery in integer paise,
    enforces hard safety guardrails, and selects the optimal bounded intervention.
    """

    def __init__(
        self,
        model: Optional[MultiActionRecoveryModel] = None,
        feature_extractor: Optional[FeatureExtractor] = None,
    ):
        self.model = model
        self.feature_extractor = feature_extractor or FeatureExtractor()

    def evaluate_case(
        self,
        case: PaymentCase,
        custom_probabilities: Optional[Dict[RecoveryAction, float]] = None,
    ) -> DecisionResult:
        """
        Evaluates all candidate actions for an observable PaymentCase and selects the optimal action.

        Parameters:
            case: Observable PaymentCase.
            custom_probabilities: Optional manual probabilities for unit testing / simulation override.

        Returns:
            DecisionResult with full audit trail and selected action.
        """
        # Validate that case has no hidden fields
        self.feature_extractor.validate_case_integrity(case)

        # 1. Obtain probabilities P(Y(a)=1 | X) for all candidate actions
        if custom_probabilities is not None:
            probs = custom_probabilities
        else:
            if self.model is None:
                raise RuntimeError("DecisionEngine requires a fitted MultiActionRecoveryModel or custom_probabilities.")
            feat_vec = self.feature_extractor.extract_features_array(case).reshape(1, -1)
            raw_pred = self.model.predict_all_positive_probas(feat_vec)
            probs = {act: float(raw_pred[act][0]) for act in ACTION_ORDER}

        # 2. Evaluate economic value and apply safety constraints for each action
        action_values: Dict[RecoveryAction, ActionValue] = {}
        allowed_actions_list: List[ActionValue] = []

        amount_paise = case.amount_paise

        for action in ACTION_ORDER:
            p_a = float(probs[action])
            cost_paise = int(ACTION_COSTS_PAISE[action])
            
            # Expected Gross Recovery = floor(P_a * amount_paise)
            gross_paise = int(math.floor(p_a * amount_paise))
            
            # Expected Net Recovery = Expected Gross - Cost
            net_paise = gross_paise - cost_paise

            # Safety Guardrails
            allowed = True
            disqualification_reason = None

            if action == RecoveryAction.RETRY and case.retry_count >= MAX_RETRY_COUNT_ALLOWED:
                allowed = False
                disqualification_reason = f"max_retries_exceeded: retry_count {case.retry_count} >= {MAX_RETRY_COUNT_ALLOWED}"
            elif action == RecoveryAction.ESCALATE and amount_paise < MIN_AMOUNT_PAISE_FOR_ESCALATE:
                allowed = False
                disqualification_reason = f"micro_ticket_protection: amount {amount_paise} paise < {MIN_AMOUNT_PAISE_FOR_ESCALATE} paise"

            # NO_ACTION is ALWAYS allowed (fundamental safety invariant)
            if action == RecoveryAction.NO_ACTION:
                allowed = True
                disqualification_reason = None

            act_val = ActionValue(
                action=action,
                predicted_probability=p_a,
                amount_paise=amount_paise,
                expected_gross_paise=gross_paise,
                action_cost_paise=cost_paise,
                expected_net_paise=net_paise,
                allowed=allowed,
                disqualification_reason=disqualification_reason,
            )
            action_values[action] = act_val
            if allowed:
                allowed_actions_list.append(act_val)

        # 3. Select action maximizing expected net recovery among allowed actions
        # Deterministic sorting: highest expected_net_paise first, tie-breaking by ACTION_ORDER index
        sorted_allowed = sorted(
            allowed_actions_list,
            key=lambda item: (-item.expected_net_paise, ACTION_ORDER.index(item.action)),
        )

        best_choice = sorted_allowed[0]

        # Calculate Decision Margin over second-best allowed action
        if len(sorted_allowed) > 1:
            decision_margin_paise = max(0, best_choice.expected_net_paise - sorted_allowed[1].expected_net_paise)
        else:
            decision_margin_paise = 0

        return DecisionResult(
            case_id=case.case_id,
            selected_action=best_choice.action,
            selected_expected_net_paise=best_choice.expected_net_paise,
            decision_margin_paise=decision_margin_paise,
            action_values=action_values,
        )

    def evaluate_cases(self, cases: List[PaymentCase]) -> List[DecisionResult]:
        """
        High-performance batch evaluation of multiple observable PaymentCases.
        Vectorizes feature extraction and probability prediction across the batch.
        """
        if not cases:
            return []

        # 1. Vectorized feature extraction and prediction
        if self.model is None:
            raise RuntimeError("evaluate_cases requires a fitted MultiActionRecoveryModel.")

        X_matrix = self.feature_extractor.transform_cases(cases)
        batch_probs = self.model.predict_all_positive_probas(X_matrix)

        results: List[DecisionResult] = []
        for i, case in enumerate(cases):
            case_probs = {act: float(batch_probs[act][i]) for act in ACTION_ORDER}
            res = self.evaluate_case(case, custom_probabilities=case_probs)
            results.append(res)

        return results

    def select_action(self, case: PaymentCase) -> RecoveryAction:
        """Convenience method returning the selected RecoveryAction."""
        return self.evaluate_case(case).selected_action
