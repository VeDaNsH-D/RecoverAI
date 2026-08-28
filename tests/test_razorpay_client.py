"""
Unit tests for Razorpay Client, test-key guardrails, authentication, timeouts, and error handling.
100% offline & deterministic via mocked transport.
"""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch
import pytest

from recovery.providers.razorpay.client import RazorpayClient, redact_secrets
from recovery.providers.razorpay.errors import (
    RazorpayAuthenticationError,
    RazorpayGatewayError,
    RazorpayRateLimitError,
    RazorpayTimeoutError,
    RazorpayValidationError,
    SecurityConfigurationError,
)
from recovery.providers.razorpay.schemas import RazorpayPaymentLinkCreateRequest


def test_razorpay_client_key_prefix_guardrail():
    """Verify that only rzp_test_ keys are permitted and rzp_live_ or invalid keys fail closed."""
    # 1. Valid test key
    client = RazorpayClient(key_id="rzp_test_1234567890", key_secret="secret_abc")
    assert client.key_id == "rzp_test_1234567890"

    # 2. Production key rejected with SecurityConfigurationError
    with pytest.raises(SecurityConfigurationError) as exc_live:
        RazorpayClient(key_id="rzp_live_1234567890", key_secret="secret_live")
    assert "Production Razorpay key" in str(exc_live.value)
    assert "strictly forbidden" in str(exc_live.value)

    # 3. Invalid prefix rejected
    with pytest.raises(SecurityConfigurationError) as exc_invalid:
        RazorpayClient(key_id="invalid_prefix_key", key_secret="secret_abc")
    assert "Invalid Razorpay key prefix" in str(exc_invalid.value)

    # 4. Missing secret rejected
    with pytest.raises(SecurityConfigurationError) as exc_missing:
        RazorpayClient(key_id="rzp_test_12345", key_secret="")
    assert "Both RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required" in str(exc_missing.value)


def test_secret_redaction_utility():
    """Verify secret scrubbing regex cleans Basic Auth headers and API keys."""
    raw = "Failed Authorization: Basic cnpwdGVzdDoxMjM0NTY= with key rzp_test_abc123 and secret secret_xyz"
    cleaned = redact_secrets(raw)
    assert "Basic [REDACTED]" in cleaned
    assert "rzp_test_***" in cleaned
    assert "rzp_test_abc123" not in cleaned


def test_razorpay_client_successful_payment_link_creation():
    """Verify standard payment link creation with mocked 200 OK HTTP response."""
    client = RazorpayClient(key_id="rzp_test_valid123", key_secret="secret_valid456")

    mock_resp_data = {
        "id": "plink_G7x60012345678",
        "short_url": "https://rzp.io/i/Xyz123",
        "status": "created",
        "amount": 500000,
        "amount_paid": 0,
        "currency": "INR",
        "reference_id": "rec_case001_idemp123",
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    req = RazorpayPaymentLinkCreateRequest(
        amount=500000,
        currency="INR",
        reference_id="rec_case001_idemp123",
        description="RecoverAI Test Payment",
    )

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        res = client.create_payment_link(req)
        assert res.id == "plink_G7x60012345678"
        assert res.short_url == "https://rzp.io/i/Xyz123"
        assert res.status == "created"
        assert res.amount == 500000

        # Verify auth header and payload sent
        sent_req = mock_urlopen.call_args[0][0]
        assert sent_req.get_header("Authorization").startswith("Basic ")
        sent_body = json.loads(sent_req.data.decode("utf-8"))
        assert sent_body["amount"] == 500000
        assert sent_body["reference_id"] == "rec_case001_idemp123"


def test_razorpay_client_duplicate_reference_idempotent_recovery():
    """Verify duplicate reference_id triggers graceful link lookup and recovery."""
    client = RazorpayClient(key_id="rzp_test_valid123", key_secret="secret_valid456")

    # 1. Mock 400 Bad Request with 'Payment link already exists'
    err_body = json.dumps({
        "error": {
            "code": "BAD_REQUEST_ERROR",
            "description": "Payment link already exists for reference_id rec_case_dup_001",
        }
    }).encode("utf-8")
    http_error = urllib.error.HTTPError(
        url="https://api.razorpay.com/v1/payment_links",
        code=400,
        msg="Bad Request",
        hdrs={},
        fp=io.BytesIO(err_body),
    )

    # 2. Mock subsequent GET /payment_links response returning existing link
    recovered_data = {
        "payment_links": [
            {
                "id": "plink_EXISTING_123",
                "short_url": "https://rzp.io/i/Existing123",
                "status": "created",
                "amount": 400000,
                "amount_paid": 0,
                "currency": "INR",
                "reference_id": "rec_case_dup_001",
            }
        ]
    }
    mock_get_resp = MagicMock()
    mock_get_resp.status = 200
    mock_get_resp.read.return_value = json.dumps(recovered_data).encode("utf-8")
    mock_get_resp.__enter__.return_value = mock_get_resp
    mock_get_resp.__exit__.return_value = None

    req = RazorpayPaymentLinkCreateRequest(
        amount=400000,
        currency="INR",
        reference_id="rec_case_dup_001",
    )

    # First call throws HTTP 400, second call returns existing link
    with patch("urllib.request.urlopen", side_effect=[http_error, mock_get_resp]):
        res = client.create_payment_link(req)
        assert res.id == "plink_EXISTING_123"
        assert res.short_url == "https://rzp.io/i/Existing123"
        assert res.status == "created"


def test_razorpay_client_error_classification():
    """Verify HTTP error codes are correctly mapped to domain exception classes."""
    client = RazorpayClient(key_id="rzp_test_valid123", key_secret="secret_valid456")

    def _make_http_err(code: int, desc: str):
        body = json.dumps({"error": {"code": "ERROR", "description": desc}}).encode("utf-8")
        return urllib.error.HTTPError(
            url="https://api.razorpay.com/v1/test",
            code=code,
            msg="Error",
            hdrs={},
            fp=io.BytesIO(body),
        )

    # 401 Unauthorized
    with patch("urllib.request.urlopen", side_effect=_make_http_err(401, "Invalid Key")):
        with pytest.raises(RazorpayAuthenticationError):
            client.get_payment_link("plink_001")

    # 429 Rate Limit
    with patch("urllib.request.urlopen", side_effect=_make_http_err(429, "Too many requests")):
        with pytest.raises(RazorpayRateLimitError):
            client.get_payment_link("plink_001")

    # 400 Bad Request
    with patch("urllib.request.urlopen", side_effect=_make_http_err(400, "Invalid amount")):
        with pytest.raises(RazorpayValidationError):
            client.get_payment_link("plink_001")

    # 500 Gateway Downtime
    with patch("urllib.request.urlopen", side_effect=_make_http_err(500, "Internal error")):
        with pytest.raises(RazorpayGatewayError):
            client.get_payment_link("plink_001")

    # Timeout
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
        with pytest.raises(RazorpayTimeoutError):
            client.get_payment_link("plink_001")


def test_razorpay_client_exact_reference_id_matching():
    """Verify get_payment_link_by_reference filters strictly by reference_id and skips unrelated links."""
    client = RazorpayClient(key_id="rzp_test_valid123", key_secret="secret_valid456")

    # Response has an unrelated link first and the matching link second
    multi_link_data = {
        "payment_links": [
            {
                "id": "plink_UNRELATED_999",
                "short_url": "https://rzp.io/i/Unrelated",
                "status": "created",
                "amount": 100000,
                "amount_paid": 0,
                "currency": "INR",
                "reference_id": "rec_different_ref_999",
            },
            {
                "id": "plink_EXACT_MATCH_123",
                "short_url": "https://rzp.io/i/ExactMatch",
                "status": "created",
                "amount": 500000,
                "amount_paid": 0,
                "currency": "INR",
                "reference_id": "rec_target_ref_123",
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(multi_link_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    # 1. Matching reference_id returns the second link, not the first
    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.get_payment_link_by_reference("rec_target_ref_123")
        assert res is not None
        assert res.id == "plink_EXACT_MATCH_123"
        assert res.reference_id == "rec_target_ref_123"

    # 2. Non-matching reference_id returns None
    with patch("urllib.request.urlopen", return_value=mock_resp):
        res_none = client.get_payment_link_by_reference("rec_non_existent_ref_000")
        assert res_none is None

