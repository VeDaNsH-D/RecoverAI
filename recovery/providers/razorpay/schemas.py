"""
Pydantic schemas for Razorpay Payment Link API and Webhook event entities.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RazorpayPaymentLinkCreateRequest(BaseModel):
    """
    Request model for POST /v1/payment_links.
    Strictly adheres to official Razorpay API contract.
    """
    amount: int = Field(..., ge=100, description="Amount in integer paise (e.g. 50000 = Rs 500.00)")
    currency: str = Field(default="INR", description="Three-letter currency code")
    accept_partial: bool = Field(default=False, description="Disable partial payments")
    description: Optional[str] = Field(default=None, description="Recovery case description")
    reference_id: Optional[str] = Field(default=None, max_length=40, description="Idempotent correlation reference")
    notes: Dict[str, Any] = Field(default_factory=dict, description="Key-value recovery context")
    notify: Dict[str, bool] = Field(default_factory=lambda: {"sms": False, "email": False})


class RazorpayPaymentLinkResponse(BaseModel):
    """
    Response model for Razorpay Payment Link entity.
    """
    id: str = Field(..., description="Official Razorpay Payment Link ID (e.g. plink_xxx)")
    short_url: Optional[str] = Field(default=None, description="Hosted checkout short URL")
    status: str = Field(..., description="Link status: created, paid, expired, cancelled")
    amount: int = Field(..., description="Target amount in integer paise")
    amount_paid: int = Field(default=0, description="Settled amount in integer paise")
    currency: str = Field(default="INR")
    reference_id: Optional[str] = None
    created_at: Optional[int] = None
    raw_response: Dict[str, Any] = Field(default_factory=dict)


class RazorpayPaymentEntity(BaseModel):
    id: str
    amount: int
    currency: str = "INR"
    status: str
    order_id: Optional[str] = None
    invoice_id: Optional[str] = None
    international: bool = False
    method: Optional[str] = None
    amount_refunded: int = 0
    captured: bool = False
    description: Optional[str] = None
    email: Optional[str] = None
    contact: Optional[str] = None
    notes: Dict[str, Any] = Field(default_factory=dict)
    fee: Optional[int] = None
    tax: Optional[int] = None
    error_code: Optional[str] = None
    error_description: Optional[str] = None
    created_at: Optional[int] = None


class RazorpayPaymentLinkEntity(BaseModel):
    id: str
    accept_partial: bool = False
    amount: int
    amount_paid: int = 0
    cancelled_at: Optional[int] = None
    created_at: Optional[int] = None
    currency: str = "INR"
    description: Optional[str] = None
    expire_by: Optional[int] = None
    expired_at: Optional[int] = None
    notes: Dict[str, Any] = Field(default_factory=dict)
    reference_id: Optional[str] = None
    short_url: Optional[str] = None
    status: str
    updated_at: Optional[int] = None
    user_id: Optional[str] = None


class RazorpaySubscriptionEntity(BaseModel):
    id: str
    plan_id: Optional[str] = None
    customer_id: Optional[str] = None
    status: str  # active, pending, halted, cancelled, completed, authenticated
    current_start: Optional[int] = None
    current_end: Optional[int] = None
    ended_at: Optional[int] = None
    quantity: int = 1
    notes: Dict[str, Any] = Field(default_factory=dict)
    charge_at: Optional[int] = None
    start_at: Optional[int] = None
    end_at: Optional[int] = None
    auth_attempts: int = 0
    total_count: Optional[int] = None
    paid_count: int = 0
    remaining_count: Optional[int] = None
    short_url: Optional[str] = None
    has_scheduled_changes: bool = False
    change_scheduled_at: Optional[int] = None
    source: Optional[str] = None
    created_at: Optional[int] = None


class RazorpayInvoiceEntity(BaseModel):
    id: str
    subscription_id: Optional[str] = None
    customer_id: Optional[str] = None
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    amount: int
    amount_paid: int = 0
    amount_due: int = 0
    currency: str = "INR"
    status: str  # issued, paid, cancelled, expired, partially_paid
    billing_start: Optional[int] = None
    billing_end: Optional[int] = None
    notes: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[int] = None


class RazorpaySubscriptionResponse(BaseModel):
    id: str
    plan_id: Optional[str] = None
    customer_id: Optional[str] = None
    status: str
    current_count: int = 1
    total_count: Optional[int] = None
    paid_count: int = 0
    remaining_count: Optional[int] = None
    auth_attempts: int = 0
    charge_at: Optional[int] = None
    short_url: Optional[str] = None
    notes: Dict[str, Any] = Field(default_factory=dict)
    raw_response: Dict[str, Any] = Field(default_factory=dict)


class RazorpayInvoiceResponse(BaseModel):
    id: str
    subscription_id: Optional[str] = None
    customer_id: Optional[str] = None
    amount: int
    amount_paid: int = 0
    amount_due: int = 0
    currency: str = "INR"
    status: str
    payment_id: Optional[str] = None
    raw_response: Dict[str, Any] = Field(default_factory=dict)


class RazorpayWebhookPayloadContainer(BaseModel):
    payment: Optional[Dict[str, Any]] = None
    payment_link: Optional[Dict[str, Any]] = None
    subscription: Optional[Dict[str, Any]] = None
    invoice: Optional[Dict[str, Any]] = None


class RazorpayWebhookEvent(BaseModel):
    """
    Standard Razorpay Webhook Event envelope.
    """
    entity: str = "event"
    account_id: Optional[str] = None
    event: str  # e.g. payment_link.paid, subscription.pending, subscription.charged, etc.
    contains: List[str] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[int] = None
