"""
Deterministic offline test fixtures for Razorpay Subscription Webhook payloads.
"""

from typing import Any, Dict, Optional


def make_subscription_pending_payload(
    subscription_id: str = "sub_test_pending_001",
    customer_id: str = "cust_sub_001",
    plan_id: str = "plan_monthly_pro",
    amount_paise: int = 299900,
    current_count: int = 1,
    total_count: int = 12,
    auth_attempts: int = 1,
    invoice_id: str = "inv_sub_001",
    payment_id: str = "pay_sub_001",
    error_code: str = "BAD_REQUEST_ERROR",
    error_description: str = "Payment failed due to insufficient funds",
    event_id: str = "evt_sub_pending_001",
) -> Dict[str, Any]:
    """Generates a realistic Razorpay subscription.pending webhook payload."""
    return {
        "entity": "event",
        "account_id": "acc_recoverai_test",
        "event": "subscription.pending",
        "contains": ["subscription", "payment", "invoice"],
        "id": event_id,
        "created_at": 1787832000,
        "payload": {
            "subscription": {
                "entity": {
                    "id": subscription_id,
                    "entity": "subscription",
                    "plan_id": plan_id,
                    "customer_id": customer_id,
                    "status": "pending",
                    "current_count": current_count,
                    "total_count": total_count,
                    "auth_attempts": auth_attempts,
                    "quantity": 1,
                    "notes": {
                        "customer_historical_success_rate": 0.88,
                        "customer_total_transactions": 15,
                        "customer_total_failures": 2,
                        "customer_tenure_months": 6,
                        "amount_paise": amount_paise,
                    },
                }
            },
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": f"order_{invoice_id}",
                    "invoice_id": invoice_id,
                    "subscription_id": subscription_id,
                    "error_code": error_code,
                    "error_description": error_description,
                }
            },
            "invoice": {
                "entity": {
                    "id": invoice_id,
                    "entity": "invoice",
                    "subscription_id": subscription_id,
                    "amount": amount_paise,
                    "amount_due": amount_paise,
                    "currency": "INR",
                    "status": "issued",
                }
            },
        },
    }


def make_subscription_charged_payload(
    subscription_id: str = "sub_test_charged_001",
    customer_id: str = "cust_sub_001",
    plan_id: str = "plan_monthly_pro",
    amount_paise: int = 299900,
    current_count: int = 1,
    total_count: int = 12,
    invoice_id: str = "inv_sub_001",
    payment_id: str = "pay_sub_captured_001",
    action_id: Optional[str] = None,
    is_payment_link: bool = False,
    event_id: str = "evt_sub_charged_001",
) -> Dict[str, Any]:
    """Generates a realistic Razorpay subscription.charged webhook payload."""
    notes = {}
    if action_id:
        notes["action_id"] = action_id

    payment_entity: Dict[str, Any] = {
        "id": payment_id,
        "entity": "payment",
        "amount": amount_paise,
        "currency": "INR",
        "status": "captured",
        "order_id": f"order_{invoice_id}",
        "invoice_id": invoice_id,
        "subscription_id": subscription_id,
        "notes": notes,
    }
    if is_payment_link:
        payment_entity["payment_link_id"] = f"plink_sub_{subscription_id[:8]}"

    return {
        "entity": "event",
        "account_id": "acc_recoverai_test",
        "event": "subscription.charged",
        "contains": ["subscription", "payment", "invoice"],
        "id": event_id,
        "created_at": 1787832100,
        "payload": {
            "subscription": {
                "entity": {
                    "id": subscription_id,
                    "entity": "subscription",
                    "plan_id": plan_id,
                    "customer_id": customer_id,
                    "status": "active",
                    "current_count": current_count,
                    "total_count": total_count,
                    "auth_attempts": 0,
                    "notes": notes,
                }
            },
            "payment": {"entity": payment_entity},
            "invoice": {
                "entity": {
                    "id": invoice_id,
                    "entity": "invoice",
                    "subscription_id": subscription_id,
                    "amount": amount_paise,
                    "amount_paid": amount_paise,
                    "amount_due": 0,
                    "currency": "INR",
                    "status": "paid",
                }
            },
        },
    }


def make_subscription_halted_payload(
    subscription_id: str = "sub_test_halted_001",
    customer_id: str = "cust_sub_001",
    plan_id: str = "plan_monthly_pro",
    amount_paise: int = 299900,
    current_count: int = 1,
    total_count: int = 12,
    auth_attempts: int = 3,
    invoice_id: str = "inv_sub_001",
    payment_id: str = "pay_sub_halted_001",
    event_id: str = "evt_sub_halted_001",
) -> Dict[str, Any]:
    """Generates a realistic Razorpay subscription.halted webhook payload."""
    return {
        "entity": "event",
        "account_id": "acc_recoverai_test",
        "event": "subscription.halted",
        "contains": ["subscription", "payment", "invoice"],
        "id": event_id,
        "created_at": 1787832200,
        "payload": {
            "subscription": {
                "entity": {
                    "id": subscription_id,
                    "entity": "subscription",
                    "plan_id": plan_id,
                    "customer_id": customer_id,
                    "status": "halted",
                    "current_count": current_count,
                    "total_count": total_count,
                    "auth_attempts": auth_attempts,
                    "notes": {
                        "retry_count": auth_attempts,
                        "amount_paise": amount_paise,
                    },
                }
            },
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": f"order_{invoice_id}",
                    "invoice_id": invoice_id,
                    "subscription_id": subscription_id,
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Recurring mandate charge retries exhausted.",
                }
            },
            "invoice": {
                "entity": {
                    "id": invoice_id,
                    "entity": "invoice",
                    "subscription_id": subscription_id,
                    "amount": amount_paise,
                    "amount_due": amount_paise,
                    "currency": "INR",
                    "status": "issued",
                }
            },
        },
    }


def make_subscription_lifecycle_payload(
    event_type: str,
    subscription_id: str = "sub_test_life_001",
    customer_id: str = "cust_sub_001",
    status: str = "active",
    event_id: str = "evt_sub_life_001",
) -> Dict[str, Any]:
    """Generates subscription lifecycle events (activated, authenticated, cancelled, completed)."""
    return {
        "entity": "event",
        "account_id": "acc_recoverai_test",
        "event": event_type,
        "contains": ["subscription"],
        "id": event_id,
        "created_at": 1787832300,
        "payload": {
            "subscription": {
                "entity": {
                    "id": subscription_id,
                    "entity": "subscription",
                    "customer_id": customer_id,
                    "status": status,
                    "current_count": 1,
                    "total_count": 12,
                    "auth_attempts": 0,
                    "notes": {},
                }
            }
        },
    }
