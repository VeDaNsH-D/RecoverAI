"""
Subscription Domain Models and Billing-Cycle Identity for RecoverAI.
Guarantees exact integer paise financial tracking, closed schemas, and deterministic correlation.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class RazorpaySubscriptionStatus(str, Enum):
    """
    Authoritative Razorpay Subscription lifecycle states.
    Strictly mirrors Razorpay documentation: authenticated, active, pending, halted, cancelled, completed.
    Plus fail-closed UNKNOWN state.
    """
    AUTHENTICATED = "authenticated"
    ACTIVE = "active"
    PENDING = "pending"
    HALTED = "halted"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class RecoverySource(str, Enum):
    """Origin of a RecoverAI recovery case."""
    ONE_OFF = "one_off"
    SUBSCRIPTION_PENDING = "subscription_pending"
    SUBSCRIPTION_HALTED = "subscription_halted"
    MANUAL_SYNC = "manual_sync"


class RecoveryResolutionSource(str, Enum):
    """
    Authoritative attribution of recovered revenue.
    Guarantees that provider automatic retries are never claimed as RecoverAI net recovery.
    """
    RECOVERAI_INTERVENTION = "recoverai_intervention"
    PROVIDER_AUTO_RETRY = "provider_auto_retry"
    NOT_RESOLVED = "not_resolved"


class SubscriptionRecord(BaseModel):
    """
    Persistent domain record of a merchant subscription entity.
    Stores only fields required for decisioning, recovery execution, reconciliation, and auditability.
    """
    model_config = ConfigDict(frozen=True)

    subscription_id: str = Field(..., description="Razorpay subscription ID (e.g. sub_xxx)")
    customer_id: str = Field(..., description="Merchant / Razorpay customer ID")
    plan_id: Optional[str] = Field(default=None, description="Plan identifier if available")
    status: RazorpaySubscriptionStatus = Field(..., description="Current Razorpay subscription state")
    current_cycle: int = Field(default=1, ge=1, description="Current billing cycle index")
    total_cycles: Optional[int] = Field(default=None, ge=1, description="Total planned billing cycles")
    amount_due_paise: int = Field(default=0, ge=0, description="Current outstanding amount in integer paise")
    currency: str = Field(default="INR", description="Three-letter currency code")
    charge_attempt_count: int = Field(default=0, ge=0, description="Number of charge attempts in current cycle")
    next_charge_at: Optional[str] = Field(default=None, description="ISO 8601 timestamp of next scheduled charge")
    last_case_id: Optional[str] = Field(default=None, description="Latest associated RecoverAI recovery case ID")
    source: str = Field(default="razorpay_test", description="Payment provider source")
    is_recoverable: bool = Field(default=True, description="Whether subscription is legally open to recovery")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Audit and diagnostic context")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="ISO 8601 creation timestamp")
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="ISO 8601 update timestamp")

    @property
    def is_terminal(self) -> bool:
        """Returns True if subscription lifecycle has ended (cancelled, completed, or unknown)."""
        return self.status in (
            RazorpaySubscriptionStatus.CANCELLED,
            RazorpaySubscriptionStatus.COMPLETED,
            RazorpaySubscriptionStatus.UNKNOWN,
        )


def derive_billing_cycle_case_id(
    subscription_id: str,
    invoice_id: Optional[str] = None,
    cycle_index: Optional[int] = None,
    payment_id: Optional[str] = None,
) -> str:
    """
    Derives a deterministic, unique recovery case identifier for a specific billing cycle.
    Prevents duplicate recovery actions across recurring cycles for the same subscription.
    
    Priority:
    1. If invoice_id is present: f"sub_{clean_sub_id}_{clean_inv_id}"
    2. Else if cycle_index is present: f"sub_{clean_sub_id}_cyc{cycle_index}"
    3. Else if payment_id is present: f"sub_{clean_sub_id}_{clean_pay_id}"
    4. Fallback: deterministic hash of available identifiers
    """
    clean_sub = (subscription_id or "sub").strip()
    
    if invoice_id and invoice_id.strip():
        clean_inv = invoice_id.strip()
        return f"sub_{clean_sub[:16]}_{clean_inv[:16]}"
    
    if cycle_index is not None and cycle_index >= 1:
        return f"sub_{clean_sub[:16]}_cyc{cycle_index}"
    
    if payment_id and payment_id.strip():
        clean_pay = payment_id.strip()
        return f"sub_{clean_sub[:16]}_{clean_pay[:16]}"
    
    # Hash fallback if only subscription_id is known
    now_month = datetime.now(timezone.utc).strftime("%Y%m")
    return f"sub_{clean_sub[:16]}_{now_month}"
