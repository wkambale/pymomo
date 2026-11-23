from __future__ import annotations

import re
from typing import Any

_UNSAFE_MSG_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")
_MAX_ERROR_MESSAGE_LEN = 512


def _sanitize_error_message(message: str) -> str:
    """Strip control/newline characters and cap length on server-controlled messages."""
    cleaned = _UNSAFE_MSG_CHAR_RE.sub(" ", str(message)).strip()
    if len(cleaned) > _MAX_ERROR_MESSAGE_LEN:
        return cleaned[: _MAX_ERROR_MESSAGE_LEN - 3].rstrip() + "..."
    return cleaned or "Bad request"


class PyMomoSDKError(Exception):
    """Base exception for all Py MoMo SDK errors."""


class AuthenticationError(PyMomoSDKError):
    """Raised when token acquisition fails (HTTP 401)."""


class MissingCredentialsError(PyMomoSDKError):
    """Raised when a product is used without configured credentials."""


class BadRequestError(PyMomoSDKError):
    """Raised on HTTP 400. Carries reason from the API response body."""

    def __init__(
        self, message: str, response_body: dict[str, Any] | None = None
    ) -> None:
        safe_message = _sanitize_error_message(message)
        super().__init__(safe_message)
        self.response_body = response_body or {}

    def __repr__(self) -> str:
        return f"BadRequestError({self.args[0]!r})"


class ResourceNotFoundError(PyMomoSDKError):
    """Raised on HTTP 404."""


class ConflictError(PyMomoSDKError):
    """Raised on HTTP 409 (duplicate request reference / conflict)."""

    def __init__(self, message: str, *, reference_id: str | None = None) -> None:
        super().__init__(message)
        self.reference_id = reference_id


class PyMomoSDKServerError(PyMomoSDKError):
    """Raised on HTTP 5xx from an upstream payment gateway API."""


class TransactionFailedError(PyMomoSDKError):
    """Raised when a polled transaction resolves to FAILED status."""

    def __init__(self, reference_id: str, reason: str | None = None) -> None:
        self.reference_id = reference_id
        self.reason = reason
        super().__init__(
            f"Transaction {reference_id} failed" + (f": {reason}" if reason else "")
        )


class WebhookVerificationError(PyMomoSDKError):
    """Raised when a webhook payload fails signature verification."""
