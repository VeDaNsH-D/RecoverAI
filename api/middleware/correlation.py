"""
Request correlation and structured access logging middleware for RecoverAI.
Extracts or generates X-Request-ID, logs operational telemetry, and records request metrics.
"""

import json
import logging
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.observability import observability_registry

logger = logging.getLogger("recoverai.api.requests")


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware managing request correlation IDs and structured access logging.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()

        # Extract client-supplied request ID or generate a new UUID
        req_id = request.headers.get("X-Request-ID")
        if not req_id or not req_id.strip():
            req_id = f"req_{uuid.uuid4().hex}"
        else:
            req_id = req_id.strip()

        # Attach request_id to request state for downstream handlers
        request.state.request_id = req_id

        # Process request through pipeline
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            observability_registry.record_request(status_code=500, duration_ms=duration_ms)
            logger.error(
                json.dumps({
                    "event": "http_request_unhandled_exception",
                    "request_id": req_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": round(duration_ms, 2),
                    "error": str(exc),
                })
            )
            raise exc

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Inject X-Request-ID into response header
        response.headers["X-Request-ID"] = req_id

        # Record operational metrics
        observability_registry.record_request(status_code=response.status_code, duration_ms=duration_ms)

        # Structured log
        log_payload = {
            "event": "http_request",
            "request_id": req_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
        }

        if response.status_code >= 500:
            logger.error(json.dumps(log_payload))
        elif response.status_code >= 400:
            logger.warning(json.dumps(log_payload))
        else:
            logger.info(json.dumps(log_payload))

        return response
