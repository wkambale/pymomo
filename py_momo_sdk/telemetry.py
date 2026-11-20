from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RequestTelemetryEvent:
    """Sanitized telemetry event emitted for outbound HTTP requests."""

    method: str
    path: str
    status_code: int | None
    latency_ms: float
    attempt: int
    correlation_id: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class WebhookTelemetryEvent:
    """Sanitized telemetry event emitted for inbound webhook verification."""

    provider: str
    verified: bool
    reason: str | None = None


@runtime_checkable
class TelemetryHook(Protocol):
    """Protocol for structured SDK observability hooks (OpenTelemetry, logging, metrics)."""

    def on_request(self, event: RequestTelemetryEvent) -> None:
        """Handle a completed or failed outbound HTTP request event."""

    def on_webhook(self, event: WebhookTelemetryEvent) -> None:
        """Handle an inbound webhook verification outcome."""
