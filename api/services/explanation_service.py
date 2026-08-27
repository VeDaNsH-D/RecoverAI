"""
Merchant explanation service for RecoverAI.
Generates deterministic, clear, merchant-friendly decision rationales strictly from observable context and decision engine outputs.
"""

from simulator.config import RecoveryAction, FailureType, PaymentMethod
from simulator.schemas.case import PaymentCase
from ml.decision_engine import DecisionResult


class ExplanationService:
    """
    Translates mathematical expected net recovery evaluations into clear, contextual merchant narratives.
    """

    @staticmethod
    def generate_merchant_explanation(
        case: PaymentCase,
        decision: DecisionResult,
    ) -> str:
        """
        Constructs a concise, professional explanation paragraph for the merchant.
        """
        sel_action = decision.selected_action
        sel_val = decision.action_values[sel_action]
        margin_inr = decision.decision_margin_inr
        net_inr = sel_val.expected_net_inr
        cost_inr = sel_val.action_cost_inr
        prob_pct = sel_val.predicted_probability * 100

        # Special Case: NO_ACTION
        if sel_action == RecoveryAction.NO_ACTION:
            if case.amount_paise < 20000:
                return (
                    f"Recommend NO ACTION because the transaction value (INR {case.amount_inr:,.2f}) is too small "
                    f"to justify intervention friction costs. Preserving operational margin by avoiding unnecessary gateway/communication fees."
                )
            return (
                f"Recommend NO ACTION because all active recovery interventions yield negative expected net return "
                f"after accounting for operational costs. Estimated passive recovery propensity is {prob_pct:.1f}%."
            )

        # Base action summary
        action_name = sel_action.value.replace("_", " ").upper()
        explanation_parts = [
            f"Recommend {action_name} because it provides the highest expected net recovery of INR {net_inr:,.2f} "
            f"(estimated {prob_pct:.1f}% recovery rate) after an operational cost of INR {cost_inr:,.2f}."
        ]

        # Contextual reasons based on observable failure & customer signals
        if case.failure_type == FailureType.TEMPORARY_FAILURE and sel_action == RecoveryAction.RETRY and case.retry_count == 0:
            explanation_parts.append(
                "Fresh temporary technical failure detected with strong customer historical reliability; automated gateway retry is the most cost-effective recovery path."
            )
        elif case.failure_type == FailureType.INSUFFICIENT_FUNDS and sel_action in (RecoveryAction.PAYMENT_LINK, RecoveryAction.REMINDER):
            explanation_parts.append(
                f"Insufficient funds failure detected; providing a flexible asynchronous payment method via {action_name} allows the customer to replenish funds or switch payment instruments."
            )
        elif case.failure_type == FailureType.INVALID_PAYMENT_METHOD and sel_action == RecoveryAction.PAYMENT_LINK:
            explanation_parts.append(
                "Payment method was rejected as invalid; sending a secure direct payment link enables the customer to update their card or VPA credentials."
            )
        elif sel_action == RecoveryAction.ESCALATE:
            explanation_parts.append(
                f"High-value ticket (INR {case.amount_inr:,.2f}) justifies manual operational escalation to maximize recovery certainty."
            )
        elif case.is_subscription:
            explanation_parts.append(
                "Recurring subscription charge prioritized for recovery to protect lifetime customer retention."
            )

        # Guardrail notes
        if case.retry_count >= 2:
            explanation_parts.append(
                "Automated retries were exhausted and suppressed by policy (retry count >= 2)."
            )
        elif case.amount_paise < 20000:
            explanation_parts.append(
                "Escalation was suppressed by policy due to micro-ticket protection (< INR 200)."
            )

        # Decision margin note
        if margin_inr > 0:
            explanation_parts.append(f"Decision margin: INR {margin_inr:,.2f} over the next-best allowed alternative.")

        return " ".join(explanation_parts)
