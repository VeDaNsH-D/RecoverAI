"""
Unit tests for RazorpayClient subscription and invoice endpoints.
100% offline with mocked network layer.
"""

from unittest.mock import MagicMock, patch
import pytest

from api.config import settings
from recovery.providers.razorpay.client import RazorpayClient
from recovery.providers.razorpay.errors import (
    RazorpayError,
    SecurityConfigurationError,
)


def test_client_enforces_test_key_prefix():
    """Verify RazorpayClient fails closed if a live production key is used."""
    settings.razorpay_key_id = "rzp_live_secret12345"
    with pytest.raises(SecurityConfigurationError):
        RazorpayClient()


def test_get_subscription_success():
    """Verify get_subscription queries GET /v1/subscriptions/{id} correctly."""
    settings.razorpay_key_id = "rzp_test_valid_key_123"
    settings.razorpay_key_secret = "test_secret_123"

    mock_resp_json = {
        "id": "sub_test_001",
        "entity": "subscription",
        "plan_id": "plan_test_001",
        "customer_id": "cust_test_001",
        "status": "pending",
        "current_count": 2,
        "total_count": 12,
        "auth_attempts": 1,
        "quantity": 1,
        "notes": {"amount_paise": 199900},
    }

    client = RazorpayClient()
    with patch.object(client, "_request", return_value=mock_resp_json) as mock_req:
        sub = client.get_subscription("sub_test_001")
        mock_req.assert_called_once_with("GET", "/subscriptions/sub_test_001")
        assert sub.id == "sub_test_001"
        assert sub.status == "pending"
        assert sub.current_count == 2
        assert sub.total_count == 12
        assert sub.auth_attempts == 1


def test_get_subscription_invoices_success():
    """Verify get_subscription_invoices queries GET /invoices?subscription_id={id} correctly."""
    settings.razorpay_key_id = "rzp_test_valid_key_123"
    settings.razorpay_key_secret = "test_secret_123"

    mock_resp_json = {
        "entity": "collection",
        "count": 1,
        "items": [
            {
                "id": "inv_test_001",
                "entity": "invoice",
                "subscription_id": "sub_test_001",
                "amount": 199900,
                "amount_due": 199900,
                "currency": "INR",
                "status": "issued",
            }
        ],
    }

    client = RazorpayClient()
    with patch.object(client, "_request", return_value=mock_resp_json) as mock_req:
        invoices = client.get_subscription_invoices("sub_test_001")
        mock_req.assert_called_once_with("GET", "/invoices", params={"subscription_id": "sub_test_001"})
        assert len(invoices) == 1
        assert invoices[0].id == "inv_test_001"
        assert invoices[0].amount == 199900
        assert invoices[0].status == "issued"


def test_get_invoice_success():
    """Verify get_invoice queries GET /invoices/{id} correctly."""
    settings.razorpay_key_id = "rzp_test_valid_key_123"
    settings.razorpay_key_secret = "test_secret_123"

    mock_resp_json = {
        "id": "inv_test_002",
        "entity": "invoice",
        "subscription_id": "sub_test_002",
        "amount": 499900,
        "amount_due": 0,
        "currency": "INR",
        "status": "paid",
    }

    client = RazorpayClient()
    with patch.object(client, "_request", return_value=mock_resp_json) as mock_req:
        inv = client.get_invoice("inv_test_002")
        mock_req.assert_called_once_with("GET", "/invoices/inv_test_002")
        assert inv.id == "inv_test_002"
        assert inv.amount == 499900
        assert inv.status == "paid"
