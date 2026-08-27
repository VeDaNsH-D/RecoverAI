"""
Production-style auditable inference engine and explanation layer for RecoverAI.
SECURITY GUARANTEE: Ingests ONLY observable PaymentCase instances.
Zero access to hidden ground truth, latent states, or future outcomes.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import json

from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from simulator.schemas.case import PaymentCase
from ml.features import FeatureExtractor, DataLeakageError
from ml.models.bundle import MultiActionRecoveryModel, ACTION_ORDER
from ml.decision_engine import ActionValue, DecisionResult, RecoveryDecisionEngine


class RecoverAIInferenceEngine:
    """
    Production-ready recovery decision inference engine.
    Orchestrates: Observable Case -> Feature Extraction -> Calibrated Action Models -> Expected Net Optimization -> Safety Guardrails -> Auditable DecisionResult.
    """

    def __init__(
        self,
        model: Optional[MultiActionRecoveryModel] = None,
        model_path: Optional[Union[str, Path]] = None,
    ):
        if model is not None:
            self._model = model
        elif model_path is not None and Path(model_path).exists():
            self._model = MultiActionRecoveryModel.load(model_path)
        else:
            self._model = None

        self._feature_extractor = FeatureExtractor()
        self._decision_engine = RecoveryDecisionEngine(
            model=self._model,
            feature_extractor=self._feature_extractor,
        )

    @property
    def is_ready(self) -> bool:
        """Returns True if the engine is loaded and ready for inference."""
        return self._model is not None and self._model.is_fitted

    def predict_decision(self, case: PaymentCase) -> DecisionResult:
        """
        Executes full inference on an observable PaymentCase.
        GUARANTEE: Ingests strictly observable context.

        Parameters:
            case: Observable PaymentCase.

        Returns:
            Auditable DecisionResult.
        """
        # Strict anti-leakage validation
        self._feature_extractor.validate_case_integrity(case)
        return self._decision_engine.evaluate_case(case)

    def explain_decision(
        self,
        case: PaymentCase,
        decision: Optional[DecisionResult] = None,
    ) -> str:
        """
        Produces a clear, human-readable, auditable explanation of the decision
        suitable for merchant dashboards, agent logs, or developer inspectability.
        """
        dec = decision or self.predict_decision(case)
        lines = []

        lines.append("=" * 75)
        lines.append(" RECOVERAI AUDITABLE DECISION REPORT")
        lines.append("=" * 75)
        lines.append(f"Case ID          : {case.case_id}")
        lines.append(f"Customer ID      : {case.customer_id}")
        lines.append(f"Transaction Value: INR {case.amount_inr:,.2f} ({case.amount_paise:,} paise)")
        lines.append(f"Payment Method   : {case.payment_method.value.upper()}")
        lines.append(f"Failure Reason   : {case.failure_type.value.replace('_', ' ').title()}")
        lines.append(f"Prior Retries    : {case.retry_count}")
        lines.append(f"Elapsed Time     : {case.hours_since_failure:.1f} hours")
        lines.append(f"Subscription     : {'Yes (Recurring)' if case.is_subscription else 'No (One-off)'}")
        lines.append("-" * 75)

        lines.append(f"RECOMMENDED ACTION: {dec.selected_action.value.upper()}")
        lines.append(f"Expected Net Value: INR {dec.selected_expected_net_inr:,.2f} ({dec.selected_expected_net_paise:,} paise)")
        lines.append(f"Decision Margin   : INR {dec.decision_margin_inr:,.2f} over next-best alternative")
        lines.append("-" * 75)

        lines.append("ACTION ECONOMICS & SAFETY AUDIT LEDGER:")
        row_fmt = "  {:<14} | {:>9} | {:>14} | {:>12} | {:>14} | {:<10}"
        lines.append(row_fmt.format("Action", "Est. Prob", "Exp. Gross", "Cost", "Exp. Net", "Safety Status"))
        lines.append("  " + "-" * 73)

        for act in ACTION_ORDER:
            av = dec.action_values[act]
            status = "ALLOWED" if av.allowed else "DISQUALIFIED"
            lines.append(row_fmt.format(
                act.value,
                f"{av.predicted_probability:.1%}",
                f"INR {av.expected_gross_inr:,.2f}",
                f"INR {av.action_cost_inr:,.2f}",
                f"INR {av.expected_net_inr:,.2f}",
                status,
            ))
            if not av.allowed and av.disqualification_reason:
                lines.append(f"    * Disqualification Note: {av.disqualification_reason}")

        lines.append("-" * 75)
        lines.append("DECISION RATIONALE:")
        sel_val = dec.action_values[dec.selected_action]
        if dec.selected_action == RecoveryAction.NO_ACTION:
            lines.append("  - All active intervention actions have negative or negligible expected net return.")
            lines.append("  - Preserving operational margin by avoiding unnecessary gateway/communication fees.")
        else:
            lines.append(
                f"  - Action '{dec.selected_action.value}' provides the highest expected net financial yield"
                f" (INR {sel_val.expected_net_inr:,.2f}) after accounting for the INR {sel_val.action_cost_inr:,.2f} friction cost."
            )
            if dec.decision_margin_paise > 0:
                lines.append(
                    f"  - Outperforms the next-best allowed action by INR {dec.decision_margin_inr:,.2f}."
                )

        lines.append("=" * 75)
        return "\n".join(lines)

    def to_dict(self, case: PaymentCase) -> Dict[str, Any]:
        """
        Returns a clean JSON-serializable dictionary representation of the inference result.
        """
        dec = self.predict_decision(case)
        return {
            "case_id": case.case_id,
            "customer_id": case.customer_id,
            "amount_inr": case.amount_inr,
            "amount_paise": case.amount_paise,
            "selected_action": dec.selected_action.value,
            "selected_expected_net_inr": dec.selected_expected_net_inr,
            "selected_expected_net_paise": dec.selected_expected_net_paise,
            "decision_margin_inr": dec.decision_margin_inr,
            "decision_margin_paise": dec.decision_margin_paise,
            "action_evaluations": {
                act.value: {
                    "predicted_probability": av.predicted_probability,
                    "expected_gross_inr": av.expected_gross_inr,
                    "expected_gross_paise": av.expected_gross_paise,
                    "action_cost_inr": av.action_cost_inr,
                    "action_cost_paise": av.action_cost_paise,
                    "expected_net_inr": av.expected_net_inr,
                    "expected_net_paise": av.expected_net_paise,
                    "allowed": av.allowed,
                    "disqualification_reason": av.disqualification_reason,
                }
                for act, av in dec.action_values.items()
            },
        }
