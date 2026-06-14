from __future__ import annotations

from typing import Any


class PyMoMoError(Exception):
    """Base exception for all PyMoMo errors."""


class AuthenticationError(PyMoMoError):
    """Raised when token acquisition fails (HTTP 401)."""


class MissingCredentialsError(PyMoMoError):
    """Raised when a product is used without configured credentials."""


class BadRequestError(PyMoMoError):
    """Raised on HTTP 400. Carries reason from the API response body."""

    def __init__(
        self, message: str, response_body: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.response_body = response_body or {}


class ResourceNotFoundError(PyMoMoError):
    """Raised on HTTP 404."""


class ConflictError(PyMoMoError):
    """Raised on HTTP 409 (duplicate X-Reference-Id)."""


class MomoServerError(PyMoMoError):
    """Raised on HTTP 5xx from the MTN API."""


class TransactionFailedError(PyMoMoError):
    """Raised when a polled transaction resolves to FAILED status."""

    def __init__(self, reference_id: str, reason: str | None = None) -> None:
        self.reference_id = reference_id
        self.reason = reason
        super().__init__(
            f"Transaction {reference_id} failed" + (f": {reason}" if reason else "")
        )


class WebhookVerificationError(PyMoMoError):
    """Raised when a webhook payload fails signature verification."""
