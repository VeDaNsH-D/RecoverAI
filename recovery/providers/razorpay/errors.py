"""
Exception hierarchy for RecoverAI Razorpay Provider Adapter.
"""


class RazorpayError(Exception):
    """Base exception for all Razorpay provider errors."""
    pass


class RazorpayAuthenticationError(RazorpayError):
    """Raised when Razorpay credentials are missing, rejected, or unauthorized (401)."""
    pass


class RazorpayValidationError(RazorpayError):
    """Raised when Razorpay rejects a request payload as invalid (400/422)."""
    pass


class RazorpayRateLimitError(RazorpayError):
    """Raised when upstream Razorpay API rate limit is exceeded (429)."""
    pass


class RazorpayGatewayError(RazorpayError):
    """Raised when upstream Razorpay encounters internal server or gateway errors (500/502/503/504)."""
    pass


class RazorpayTimeoutError(RazorpayError):
    """Raised when an HTTP request to Razorpay times out."""
    pass


class SecurityConfigurationError(RazorpayError):
    """Raised when insecure or non-test credentials (e.g. rzp_live_) are detected."""
    pass
