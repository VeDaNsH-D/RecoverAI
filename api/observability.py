"""
Thread-safe in-memory operational metrics collector for RecoverAI API.
Provides operational metrics without exposing model internals, latent variables, or customer PII.
"""

import threading
import time
from typing import Any, Dict


class ObservabilityRegistry:
    """
    In-memory operational metrics collector for production observability.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._requests_total = 0
        self._responses_2xx = 0
        self._responses_4xx = 0
        self._responses_5xx = 0
        self._total_latency_ms = 0.0
        self._decisions_generated = 0
        self._actions_dispatched = 0
        self._execution_failures = 0
        self._outcomes_recorded = 0

    def record_request(self, status_code: int, duration_ms: float) -> None:
        """Records an HTTP request and response status."""
        with self._lock:
            self._requests_total += 1
            self._total_latency_ms += duration_ms
            if 200 <= status_code < 300:
                self._responses_2xx += 1
            elif 400 <= status_code < 500:
                self._responses_4xx += 1
            elif status_code >= 500:
                self._responses_5xx += 1

    def record_decision(self) -> None:
        """Increments decision generation counter."""
        with self._lock:
            self._decisions_generated += 1

    def record_action_dispatch(self, status: str) -> None:
        """Increments action dispatch counters."""
        with self._lock:
            self._actions_dispatched += 1
            if status == "FAILED":
                self._execution_failures += 1

    def record_outcome(self) -> None:
        """Increments outcome recording counter."""
        with self._lock:
            self._outcomes_recorded += 1

    def get_metrics(self) -> Dict[str, Any]:
        """Returns snapshot of operational metrics."""
        with self._lock:
            uptime = time.time() - self._start_time
            avg_latency = (self._total_latency_ms / self._requests_total) if self._requests_total > 0 else 0.0
            return {
                "uptime_seconds": round(uptime, 2),
                "requests_total": self._requests_total,
                "responses_2xx": self._responses_2xx,
                "responses_4xx": self._responses_4xx,
                "responses_5xx": self._responses_5xx,
                "avg_latency_ms": round(avg_latency, 2),
                "decisions_generated": self._decisions_generated,
                "actions_dispatched": self._actions_dispatched,
                "execution_failures": self._execution_failures,
                "outcomes_recorded": self._outcomes_recorded,
            }

    def reset_for_testing(self) -> None:
        """Resets counters for test isolation."""
        with self._lock:
            self._start_time = time.time()
            self._requests_total = 0
            self._responses_2xx = 0
            self._responses_4xx = 0
            self._responses_5xx = 0
            self._total_latency_ms = 0.0
            self._decisions_generated = 0
            self._actions_dispatched = 0
            self._execution_failures = 0
            self._outcomes_recorded = 0


# Global observability registry instance
observability_registry = ObservabilityRegistry()
