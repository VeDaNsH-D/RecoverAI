"""
Operational observability metrics endpoint for RecoverAI API.
Exposes runtime traffic, status distributions, and execution counters.
"""

from datetime import datetime, timezone
from fastapi import APIRouter
from api.schemas import ObservabilityMetricsResponse
from api.observability import observability_registry

router = APIRouter()


@router.get(
    "/observability/metrics",
    response_model=ObservabilityMetricsResponse,
    tags=["Observability"],
)
async def get_observability_metrics():
    """
    Returns runtime operational metrics and request performance telemetry.
    Does NOT expose training labels, model weights, simulator latent variables, or customer PII.
    """
    metrics = observability_registry.get_metrics()
    return ObservabilityMetricsResponse(
        uptime_seconds=metrics["uptime_seconds"],
        requests_total=metrics["requests_total"],
        responses_2xx=metrics["responses_2xx"],
        responses_4xx=metrics["responses_4xx"],
        responses_5xx=metrics["responses_5xx"],
        avg_latency_ms=metrics["avg_latency_ms"],
        decisions_generated=metrics["decisions_generated"],
        actions_dispatched=metrics["actions_dispatched"],
        execution_failures=metrics["execution_failures"],
        outcomes_recorded=metrics["outcomes_recorded"],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
