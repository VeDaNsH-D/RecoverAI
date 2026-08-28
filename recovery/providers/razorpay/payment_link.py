"""
Razorpay Payment Link Action Provider adapter for RecoverAI.
Implements BaseActionProvider interface for executing RecoveryAction.PAYMENT_LINK in TEST MODE.
"""

from typing import Optional
from simulator.config import RecoveryAction, ACTION_COSTS_PAISE
from recovery.actions.base import BaseActionProvider, ExecutionResult
from recovery.models import (
    ActionExecutionStatus,
    DecisionRecord,
    RecoveryCaseRecord,
)
from recovery.providers.razorpay.client import RazorpayClient, redact_secrets
from recovery.providers.razorpay.schemas import RazorpayPaymentLinkCreateRequest


class RazorpayPaymentLinkProvider(BaseActionProvider):
    """
    Action provider for generating real Razorpay TEST MODE Payment Links.
    Translates observable case data to Razorpay API payloads without mutating decision or state authority.
    """

    def __init__(self, client: Optional[RazorpayClient] = None):
        self.client = client or RazorpayClient()

    @property
    def action(self) -> RecoveryAction:
        return RecoveryAction.PAYMENT_LINK

    @property
    def cost_paise(self) -> int:
        return ACTION_COSTS_PAISE[RecoveryAction.PAYMENT_LINK]

    def execute(
        self,
        case: RecoveryCaseRecord,
        decision: DecisionRecord,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Executes payment link generation against Razorpay TEST API.
        Enforces integer paise financial safety and clean error mapping to EXECUTION_FAILED.
        """
        # Validate integer paise amount
        if case.amount_paise < 100:
            return ExecutionResult(
                status=ActionExecutionStatus.FAILED,
                provider_reference="",
                cost_paise=0,
                error_message=f"Amount {case.amount_paise} paise is below Razorpay minimum transaction threshold of 100 paise (Rs 1.00).",
                metadata={"error_type": "ValidationError"},
            )

        # Construct reference_id bounded to 40 characters
        clean_case_id = (case.case_id or "case")[:16]
        clean_idemp = (idempotency_key or "idemp")[:12]
        reference_id = f"rec_{clean_case_id}_{clean_idemp}"

        req = RazorpayPaymentLinkCreateRequest(
            amount=case.amount_paise,
            currency="INR",
            accept_partial=False,
            description=f"RecoverAI Payment Recovery for Case {case.case_id}",
            reference_id=reference_id,
            notes={
                "case_id": case.case_id,
                "decision_id": decision.decision_id,
                "customer_id": case.customer_id,
            },
            notify={"sms": False, "email": False},
        )

        try:
            resp = self.client.create_payment_link(req)
            return ExecutionResult(
                status=ActionExecutionStatus.EXECUTED,
                provider_reference=resp.id,
                cost_paise=self.cost_paise,
                metadata={
                    "short_url": resp.short_url,
                    "provider_status": resp.status,
                    "reference_id": resp.reference_id,
                    "provider": "razorpay_test",
                },
            )
        except Exception as exc:
            sanitized_err = redact_secrets(str(exc))
            return ExecutionResult(
                status=ActionExecutionStatus.FAILED,
                provider_reference="",
                cost_paise=0,
                error_message=sanitized_err,
                metadata={
                    "error_type": exc.__class__.__name__,
                    "provider": "razorpay_test",
                },
            )
