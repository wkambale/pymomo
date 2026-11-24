from __future__ import annotations

import re
from typing import Any

_UNSAFE_MSG_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")
_MAX_ERROR_MESSAGE_LEN = 512
_SENSITIVE_BODY_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "token",
        "id_token",
        "api_key",
        "apikey",
        "client_secret",
        "consumer_secret",
        "subscription_key",
        "ocp-apim-subscription-key",
        "secret",
        "secret_key",
        "webhook_secret",
        "webhook_hash",
        "passkey",
        "password",
        "pin",
        "authorization",
        "security_credential",
        "securitycredential",
        "auth_req_id",
        "merchant_key",
    }
)


def _sanitize_error_message(message: str, *, default: str = "Bad request") -> str:
    """Strip control/newline characters and cap length on server-controlled messages."""
    cleaned = _UNSAFE_MSG_CHAR_RE.sub(" ", str(message)).strip()
    if len(cleaned) > _MAX_ERROR_MESSAGE_LEN:
        return cleaned[: _MAX_ERROR_MESSAGE_LEN - 3].rstrip() + "..."
    return cleaned or default


def _redact_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "<truncated>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key_str = str(k)
            if key_str.lower() in _SENSITIVE_BODY_KEYS:
                out[key_str] = "<redacted>"
            else:
                out[key_str] = _redact_value(v, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_redact_value(item, depth=depth + 1) for item in value[:25]]
    return value


def _redact_response_body(body: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of an upstream response dict with sensitive keys redacted."""
    if not isinstance(body, dict) or not body:
        return {}
    redacted = _redact_value(body)
    return redacted if isinstance(redacted, dict) else {}


class PyMomoSDKError(Exception):
    """Base exception for all Py MoMo SDK errors."""

    def __init__(
        self,
        message: str = "",
        *,
        reference_id: str | None = None,
        status_code: int | None = None,
        error_code: str | None = None,
        reason: str | None = None,
        response_body: dict[str, Any] | None = None,
        provider: str | None = None,
        attempted_references: list[dict[str, str | None]] | None = None,
    ) -> None:
        safe_message = _sanitize_error_message(message, default="") if message else ""
        super().__init__(safe_message)
        self.reference_id = reference_id
        self.status_code = status_code
        self.error_code = (
            _sanitize_error_message(error_code, default="") or None
            if error_code is not None
            else None
        )
        self.reason = (
            _sanitize_error_message(reason, default="") or None
            if reason is not None
            else None
        )
        self.response_body: dict[str, Any] = _redact_response_body(response_body)
        self.provider = provider
        self.attempted_references: list[dict[str, str | None]] = (
            list(attempted_references) if attempted_references is not None else []
        )

    def __repr__(self) -> str:
        msg = self.args[0] if self.args else ""
        parts = [repr(msg)]
        if self.reference_id is not None:
            parts.append(f"reference_id={self.reference_id!r}")
        if self.status_code is not None:
            parts.append(f"status_code={self.status_code!r}")
        if self.error_code is not None:
            parts.append(f"error_code={self.error_code!r}")
        if self.provider is not None:
            parts.append(f"provider={self.provider!r}")
        return f"{self.__class__.__name__}({', '.join(parts)})"


class AuthenticationError(PyMomoSDKError):
    """Raised when authentication or token acquisition fails (HTTP 401)."""


class MissingCredentialsError(PyMomoSDKError):
    """Raised when a product is used without configured credentials."""


class BadRequestError(PyMomoSDKError):
    """Raised on HTTP 400 or 422. Carries structured reason from the API response body."""

    def __init__(
        self,
        message: str,
        response_body: dict[str, Any] | None = None,
        *,
        reference_id: str | None = None,
        status_code: int | None = 400,
        error_code: str | None = None,
        reason: str | None = None,
        provider: str | None = None,
    ) -> None:
        safe_message = _sanitize_error_message(message, default="Bad request")
        super().__init__(
            safe_message,
            reference_id=reference_id,
            status_code=status_code,
            error_code=error_code,
            reason=reason or safe_message,
            response_body=response_body,
            provider=provider,
        )


class ResourceNotFoundError(PyMomoSDKError):
    """Raised on HTTP 404."""


class ConflictError(PyMomoSDKError):
    """Raised on HTTP 409 (duplicate request reference / conflict)."""

    def __init__(
        self,
        message: str,
        *,
        reference_id: str | None = None,
        status_code: int | None = 409,
        error_code: str | None = None,
        reason: str | None = None,
        response_body: dict[str, Any] | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__(
            message,
            reference_id=reference_id,
            status_code=status_code,
            error_code=error_code,
            reason=reason,
            response_body=response_body,
            provider=provider,
        )


class PyMomoSDKServerError(PyMomoSDKError):
    """Raised on HTTP 5xx from an upstream payment gateway API."""


class TransactionFailedError(PyMomoSDKError):
    """Raised when a polled or synchronous transaction resolves to FAILED status."""

    def __init__(
        self,
        reference_id: str,
        reason: str | None = None,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        response_body: dict[str, Any] | None = None,
        provider: str | None = None,
    ) -> None:
        safe_reason = (
            _sanitize_error_message(reason, default="") or None
            if reason is not None
            else None
        )
        msg = f"Transaction {reference_id} failed" + (
            f": {safe_reason}" if safe_reason else ""
        )
        super().__init__(
            msg,
            reference_id=reference_id,
            status_code=status_code,
            error_code=error_code,
            reason=safe_reason,
            response_body=response_body,
            provider=provider,
        )


class WebhookVerificationError(PyMomoSDKError):
    """Raised when a webhook payload fails signature verification."""
