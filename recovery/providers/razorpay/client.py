"""
Zero-dependency HTTP Client adapter for Razorpay TEST MODE REST API.
Enforces strict test-mode key prefix guardrail (rzp_test_), timeout handling, and secret redaction.
"""

import base64
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request

from api.config import settings
from recovery.providers.razorpay.errors import (
    RazorpayAuthenticationError,
    RazorpayError,
    RazorpayGatewayError,
    RazorpayRateLimitError,
    RazorpayTimeoutError,
    RazorpayValidationError,
    SecurityConfigurationError,
)
from recovery.providers.razorpay.schemas import (
    RazorpayPaymentLinkCreateRequest,
    RazorpayPaymentLinkResponse,
    RazorpaySubscriptionResponse,
    RazorpayInvoiceResponse,
)

logger = logging.getLogger("recoverai.razorpay.client")


def redact_secrets(text: str) -> str:
    """Sanitizes API keys, Basic Auth tokens, and secrets from logs and error strings."""
    if not text:
        return ""
    # Redact Basic Auth headers
    text = re.sub(r"(Basic\s+)[A-Za-z0-9+/=]+", r"\1[REDACTED]", text, flags=re.IGNORECASE)
    # Redact rzp_test keys and secrets
    text = re.sub(r"(rzp_test_[a-zA-Z0-9]+)", r"rzp_test_***", text)
    text = re.sub(r"(rzp_live_[a-zA-Z0-9]+)", r"rzp_live_***", text)
    return text


class RazorpayClient:
    """
    Client for interacting with Razorpay TEST MODE REST API.
    """

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        self.key_id = key_id or settings.razorpay_key_id
        self.key_secret = key_secret or settings.razorpay_key_secret
        self.base_url = (base_url or settings.razorpay_base_url).rstrip("/")
        self.timeout = timeout_seconds or settings.razorpay_timeout_seconds

        self._validate_key_guardrail()

    def _validate_key_guardrail(self) -> None:
        """
        Enforces strict test-mode credential safety guardrails.
        Fails closed on missing, production (rzp_live_), or malformed keys.
        """
        # If in mock mode, keys may be absent until client is explicitly invoked
        if not self.key_id and not self.key_secret:
            return

        if not self.key_id or not self.key_secret:
            raise SecurityConfigurationError(
                "Both RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required for Razorpay client."
            )

        key_id_clean = self.key_id.strip()
        if key_id_clean.startswith("rzp_live_"):
            raise SecurityConfigurationError(
                f"Production Razorpay key '{redact_secrets(key_id_clean)}' is strictly forbidden in RecoverAI Test-Mode adapter."
            )

        if not key_id_clean.startswith("rzp_test_"):
            raise SecurityConfigurationError(
                f"Invalid Razorpay key prefix '{redact_secrets(key_id_clean)}'. RecoverAI Test-Mode requires a key starting with 'rzp_test_'."
            )

    def _get_auth_header(self) -> str:
        if not self.key_id or not self.key_secret:
            raise RazorpayAuthenticationError("Razorpay credentials are not configured.")
        raw_auth = f"{self.key_id.strip()}:{self.key_secret.strip()}".encode("utf-8")
        encoded = base64.b64encode(raw_auth).decode("ascii")
        return f"Basic {encoded}"

    def _request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Executes HTTP request to Razorpay API with strict error classification and timing telemetry.
        """
        self._validate_key_guardrail()

        url = f"{self.base_url}{endpoint}"
        if params:
            query_string = urllib.parse.urlencode(params)
            url = f"{url}?{query_string}"

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "RecoverAI-Payment-Recovery/1.0",
            "Authorization": self._get_auth_header(),
        }

        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method.upper())

        start_time = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                resp_bytes = response.read()
                resp_json = json.loads(resp_bytes.decode("utf-8"))
                logger.debug(
                    "Razorpay API Call Succeeded | method=%s endpoint=%s status=%d latency_ms=%.2f",
                    method,
                    endpoint,
                    response.status,
                    latency_ms,
                )
                return resp_json
        except urllib.error.HTTPError as http_err:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            error_body = ""
            error_json = {}
            try:
                error_body = http_err.read().decode("utf-8")
                error_json = json.loads(error_body)
            except Exception:
                pass

            err_msg = error_json.get("error", {}).get("description") or error_body or http_err.reason
            err_msg_clean = redact_secrets(str(err_msg))

            logger.warning(
                "Razorpay API Error | method=%s endpoint=%s status=%d err=%s latency_ms=%.2f",
                method,
                endpoint,
                http_err.code,
                err_msg_clean,
                latency_ms,
            )

            if http_err.code == 401:
                raise RazorpayAuthenticationError(f"Razorpay Authentication Failed: {err_msg_clean}") from http_err
            elif http_err.code == 429:
                raise RazorpayRateLimitError(f"Razorpay Rate Limit Exceeded: {err_msg_clean}") from http_err
            elif http_err.code in (400, 422):
                raise RazorpayValidationError(f"Razorpay Request Validation Failed ({http_err.code}): {err_msg_clean}") from http_err
            elif http_err.code in (500, 502, 503, 504):
                raise RazorpayGatewayError(f"Razorpay Upstream Gateway Error ({http_err.code}): {err_msg_clean}") from http_err
            else:
                raise RazorpayError(f"Razorpay API Error ({http_err.code}): {err_msg_clean}") from http_err
        except (urllib.error.URLError, TimeoutError, OSError) as net_err:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            err_str = redact_secrets(str(net_err))
            logger.error(
                "Razorpay Network / Timeout Error | method=%s endpoint=%s err=%s latency_ms=%.2f",
                method,
                endpoint,
                err_str,
                latency_ms,
            )
            raise RazorpayTimeoutError(f"Razorpay Network / Timeout Error: {err_str}") from net_err

    def create_payment_link(self, req: RazorpayPaymentLinkCreateRequest) -> RazorpayPaymentLinkResponse:
        """
        Creates a payment link via POST /v1/payment_links.
        Handles idempotent recovery on duplicate reference_id.
        """
        payload = req.model_dump(exclude_none=True)
        try:
            raw = self._request("POST", "/payment_links", payload=payload)
        except RazorpayValidationError as val_err:
            # Check if this error is duplicate reference_id
            if req.reference_id:
                err_str = str(val_err).lower()
                if "already exists" in err_str or "duplicate" in err_str or "reference_id" in err_str:
                    logger.info(
                        "Duplicate reference_id detected on Razorpay ('%s'). Attempting idempotent retrieval.",
                        req.reference_id,
                    )
                    recovered = self.get_payment_link_by_reference(req.reference_id)
                    if recovered and recovered.reference_id == req.reference_id:
                        return recovered
            raise

        return RazorpayPaymentLinkResponse(
            id=raw.get("id", ""),
            short_url=raw.get("short_url"),
            status=raw.get("status", "created"),
            amount=raw.get("amount", req.amount),
            amount_paid=raw.get("amount_paid", 0),
            currency=raw.get("currency", "INR"),
            reference_id=raw.get("reference_id"),
            created_at=raw.get("created_at"),
            raw_response=raw,
        )

    def get_payment_link(self, payment_link_id: str) -> RazorpayPaymentLinkResponse:
        """
        Retrieves status of a payment link via GET /v1/payment_links/{id}.
        """
        raw = self._request("GET", f"/payment_links/{payment_link_id}")
        return RazorpayPaymentLinkResponse(
            id=raw.get("id", payment_link_id),
            short_url=raw.get("short_url"),
            status=raw.get("status", "created"),
            amount=raw.get("amount", 0),
            amount_paid=raw.get("amount_paid", 0),
            currency=raw.get("currency", "INR"),
            reference_id=raw.get("reference_id"),
            created_at=raw.get("created_at"),
            raw_response=raw,
        )

    def get_payment_link_by_reference(self, reference_id: str) -> Optional[RazorpayPaymentLinkResponse]:
        """
        Retrieves payment link by reference_id query.
        Guarantees that returned link strictly matches the requested reference_id.
        """
        try:
            raw = self._request("GET", "/payment_links", params={"reference_id": reference_id})
            links = raw.get("payment_links", [])
            for link in links:
                if link.get("reference_id") == reference_id:
                    return RazorpayPaymentLinkResponse(
                        id=link.get("id", ""),
                        short_url=link.get("short_url"),
                        status=link.get("status", "created"),
                        amount=link.get("amount", 0),
                        amount_paid=link.get("amount_paid", 0),
                        currency=link.get("currency", "INR"),
                        reference_id=link.get("reference_id"),
                        created_at=link.get("created_at"),
                        raw_response=link,
                    )
        except Exception as err:
            logger.warning("Failed to look up payment link by reference_id '%s': %s", reference_id, redact_secrets(str(err)))
        return None

    def get_subscription(self, subscription_id: str) -> RazorpaySubscriptionResponse:
        """
        Retrieves subscription details via GET /v1/subscriptions/{id}.
        """
        raw = self._request("GET", f"/subscriptions/{subscription_id}")
        return RazorpaySubscriptionResponse(
            id=raw.get("id", subscription_id),
            plan_id=raw.get("plan_id"),
            customer_id=raw.get("customer_id"),
            status=raw.get("status", "active"),
            current_count=raw.get("current_count", 1),
            total_count=raw.get("total_count"),
            paid_count=raw.get("paid_count", 0),
            remaining_count=raw.get("remaining_count"),
            auth_attempts=raw.get("auth_attempts", 0),
            charge_at=raw.get("charge_at"),
            short_url=raw.get("short_url"),
            notes=raw.get("notes", {}),
            raw_response=raw,
        )

    def get_subscription_invoices(self, subscription_id: str) -> List[RazorpayInvoiceResponse]:
        """
        Retrieves all invoices for a subscription via GET /v1/invoices?subscription_id={id}.
        """
        raw = self._request("GET", "/invoices", params={"subscription_id": subscription_id})
        items = raw.get("items", []) or raw.get("invoices", [])
        results = []
        for inv in items:
            results.append(
                RazorpayInvoiceResponse(
                    id=inv.get("id", ""),
                    subscription_id=inv.get("subscription_id", subscription_id),
                    customer_id=inv.get("customer_id"),
                    amount=inv.get("amount", 0),
                    amount_paid=inv.get("amount_paid", 0),
                    amount_due=inv.get("amount_due", 0),
                    currency=inv.get("currency", "INR"),
                    status=inv.get("status", "issued"),
                    payment_id=inv.get("payment_id"),
                    notes=inv.get("notes", {}),
                    raw_response=inv,
                )
            )
        return results

    def get_invoice(self, invoice_id: str) -> RazorpayInvoiceResponse:
        """
        Retrieves a single invoice via GET /v1/invoices/{id}.
        """
        raw = self._request("GET", f"/invoices/{invoice_id}")
        return RazorpayInvoiceResponse(
            id=raw.get("id", invoice_id),
            subscription_id=raw.get("subscription_id"),
            customer_id=raw.get("customer_id"),
            amount=raw.get("amount", 0),
            amount_paid=raw.get("amount_paid", 0),
            amount_due=raw.get("amount_due", 0),
            currency=raw.get("currency", "INR"),
            status=raw.get("status", "issued"),
            payment_id=raw.get("payment_id"),
            notes=raw.get("notes", {}),
            raw_response=raw,
        )
