from __future__ import annotations

import logging
import math
import re
import secrets
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from py_momo_sdk.auth import TokenCache
from py_momo_sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    PyMomoSDKError,
    PyMomoSDKServerError,
    ResourceNotFoundError,
)
from py_momo_sdk.telemetry import RequestTelemetryEvent, TelemetryHook
from py_momo_sdk.utils import (
    validate_base_url,
    validate_matching_origin,
    validate_max_retries,
    validate_request_path,
    validate_retry_backoff,
    validate_timeout,
)

if TYPE_CHECKING:
    from typing_extensions import Self

logger = logging.getLogger("py_momo_sdk.http")

_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEFAULT_MAX_RESPONSE_BYTES = 1_048_576  # 1 MiB
_ACCOUNTHOLDER_PATH_RE = re.compile(r"(/accountholder/[^/]+/)[^/?#]+")
_APIUSER_PATH_RE = re.compile(r"(/v1_0/apiuser/)[^/?#]+")


def _get_header_ci(headers: Mapping[str, str], name: str) -> str | None:
    target = name.lower()
    for k, v in headers.items():
        if k.lower() == target:
            return v
    return None


def _sanitize_telemetry_path(path: str) -> str:
    raw_path = path.split("?", 1)[0]
    sanitized = _ACCOUNTHOLDER_PATH_RE.sub(r"\1<redacted>", raw_path)
    return _APIUSER_PATH_RE.sub(r"\1<redacted>", sanitized)


def _extract_bearer_token(headers: Mapping[str, str]) -> str | None:
    """Extract Bearer token from Authorization header case-insensitively."""
    auth_val = _get_header_ci(headers, "Authorization") or ""
    scheme, sep, token = auth_val.partition(" ")
    if sep and scheme.lower() == "bearer" and token:
        return token
    return None


def _is_retryable_request(
    method: str, headers: dict[str, str], *, idempotent: bool | None = None
) -> bool:
    if idempotent is not None:
        return idempotent
    if method.upper() in _IDEMPOTENT_METHODS:
        return True
    for header_name in ("Idempotency-Key", "X-Reference-Id"):
        val = _get_header_ci(headers, header_name)
        if val and val.strip():
            return True
    return False


def _parse_retry_after(raw_value: str) -> float | None:
    """Parse RFC 9110 Retry-After delay-seconds or HTTP-date into clamped seconds."""
    stripped = raw_value.strip()
    if not stripped:
        return None
    try:
        parsed = float(stripped)
        if math.isfinite(parsed) and parsed >= 0.0:
            return min(parsed, 30.0)
        return None
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(stripped)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = (dt - datetime.now(timezone.utc)).total_seconds()
        return min(max(delta, 0.0), 30.0)
    except (TypeError, ValueError, OverflowError):
        return None


def _compute_retry_delay(
    attempt: int, base_backoff: float, response: httpx.Response | None
) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            parsed = _parse_retry_after(retry_after)
            if parsed is not None:
                if parsed == 0.0:
                    return 0.0
                max_jitter_ms = int(min(250.0, parsed * 100.0))
                jitter = (
                    secrets.randbelow(max_jitter_ms) / 1000.0
                    if max_jitter_ms > 0
                    else 0.0
                )
                return float(min(parsed + jitter, 30.0))
    jitter = secrets.randbelow(250) / 1000.0
    exp = min(max(attempt, 0), 30)
    return float(min(base_backoff * (2**exp) + jitter, 30.0))


class _ResponseTooLargeError(PyMomoSDKError):
    """Internal marker for responses exceeding max_response_bytes."""


class HttpClient:
    """Thin wrapper around httpx.Client with retry logic and error mappings."""

    def __init__(
        self,
        base_url: str,
        timeout: float | httpx.Timeout,
        *,
        max_retries: int = 0,
        retry_backoff: float = 0.5,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        client: httpx.Client | None = None,
        limits: httpx.Limits | None = None,
        telemetry: TelemetryHook | None = None,
        provider_name: str | None = None,
    ) -> None:
        validated_url = validate_base_url(base_url)
        validated_timeout: float | httpx.Timeout = (
            timeout if isinstance(timeout, httpx.Timeout) else validate_timeout(timeout)
        )
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes <= 0
        ):
            raise ValueError("max_response_bytes must be a positive integer")
        self._validated_base_url = validated_url.rstrip("/")
        self._max_retries = validate_max_retries(max_retries)
        self._retry_backoff = validate_retry_backoff(retry_backoff)
        self._max_response_bytes = max_response_bytes
        self._telemetry = telemetry
        self._provider_name = provider_name
        self._owns_client = client is None
        if client is not None:
            injected_base = str(client.base_url)
            if injected_base:
                validate_base_url(injected_base)
                validate_matching_origin(validated_url, injected_base)
            self._client = client
        else:
            client_kwargs: dict[str, Any] = {
                "base_url": validated_url,
                "timeout": validated_timeout,
                "follow_redirects": False,
            }
            if limits is not None:
                client_kwargs["limits"] = limits
            self._client = httpx.Client(**client_kwargs)

    def _emit_telemetry(
        self,
        method: str,
        path: str,
        status_code: int | None,
        started: float,
        attempt: int,
        correlation_id: str | None,
        error_type: str | None = None,
    ) -> None:
        if self._telemetry is None:
            return
        try:
            self._telemetry.on_request(
                RequestTelemetryEvent(
                    method=method,
                    path=_sanitize_telemetry_path(path),
                    status_code=status_code,
                    latency_ms=(time.monotonic() - started) * 1000.0,
                    attempt=attempt,
                    correlation_id=correlation_id,
                    error_type=error_type,
                )
            )
        except Exception:
            logger.warning(
                "Telemetry hook on_request raised an exception", exc_info=True
            )

    def _execute_bounded_request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: Any,
        data: Any,
    ) -> httpx.Response:
        target = (
            path if str(self._client.base_url) else f"{self._validated_base_url}{path}"
        )
        req = self._client.build_request(
            method, target, headers=headers, json=json, data=data
        )
        response = self._client.send(req, stream=True, follow_redirects=False)
        try:
            cl_header = response.headers.get("Content-Length")
            if cl_header is not None:
                try:
                    if int(cl_header) > self._max_response_bytes:
                        raise _ResponseTooLargeError(
                            f"Response body exceeded maximum allowed size of {self._max_response_bytes} bytes"
                        )
                except ValueError:
                    pass
            buf = bytearray()
            for chunk in response.iter_bytes():
                if len(buf) + len(chunk) > self._max_response_bytes:
                    raise _ResponseTooLargeError(
                        f"Response body exceeded maximum allowed size of {self._max_response_bytes} bytes"
                    )
                buf.extend(chunk)
            response._content = bytes(buf)
        finally:
            response.close()
        return response

    def _send_with_transient_retries(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: Any,
        data: Any,
        timeout_msg: str,
        conn_msg: str,
        idempotent: bool | None = None,
        max_retries_override: int | None = None,
        reference_id: str | None = None,
    ) -> tuple[httpx.Response, int]:
        effective_retries = (
            self._max_retries if max_retries_override is None else max_retries_override
        )
        can_retry = effective_retries > 0 and _is_retryable_request(
            method, headers, idempotent=idempotent
        )
        attempts = (effective_retries + 1) if can_retry else 1
        correlation_id = (
            reference_id
            or _get_header_ci(headers, "X-Reference-Id")
            or _get_header_ci(headers, "Idempotency-Key")
        )

        for attempt in range(attempts):
            started = time.monotonic()
            try:
                response = self._execute_bounded_request(
                    method, path, headers=headers, json=json, data=data
                )
            except _ResponseTooLargeError as exc:
                self._emit_telemetry(
                    method,
                    path,
                    None,
                    started,
                    attempt + 1,
                    correlation_id,
                    "ResponseTooLargeError",
                )
                if exc.reference_id is None and correlation_id is not None:
                    exc.reference_id = correlation_id
                if exc.provider is None and self._provider_name is not None:
                    exc.provider = self._provider_name
                raise
            except httpx.TimeoutException as exc:
                exc_name = type(exc).__name__
                self._emit_telemetry(
                    method,
                    path,
                    None,
                    started,
                    attempt + 1,
                    correlation_id,
                    "TimeoutException",
                )
                if attempt + 1 < attempts:
                    time.sleep(_compute_retry_delay(attempt, self._retry_backoff, None))
                    continue
                raise PyMomoSDKError(
                    f"{timeout_msg} ({exc_name})",
                    reference_id=correlation_id,
                    reason=exc_name,
                    provider=self._provider_name,
                ) from None
            except httpx.RequestError as exc:
                exc_name = type(exc).__name__
                self._emit_telemetry(
                    method,
                    path,
                    None,
                    started,
                    attempt + 1,
                    correlation_id,
                    "RequestError",
                )
                if attempt + 1 < attempts:
                    time.sleep(_compute_retry_delay(attempt, self._retry_backoff, None))
                    continue
                raise PyMomoSDKError(
                    f"{conn_msg} ({exc_name})",
                    reference_id=correlation_id,
                    reason=exc_name,
                    provider=self._provider_name,
                ) from None

            self._emit_telemetry(
                method,
                path,
                response.status_code,
                started,
                attempt + 1,
                correlation_id,
            )
            if (
                response.status_code in _RETRYABLE_STATUS_CODES
                and attempt + 1 < attempts
            ):
                delay = _compute_retry_delay(attempt, self._retry_backoff, response)
                logger.debug(
                    "Transient HTTP %s on %s %s; retrying in %.2fs",
                    response.status_code,
                    method,
                    _sanitize_telemetry_path(path),
                    delay,
                )
                time.sleep(delay)
                continue
            return response, attempt + 1

        raise AssertionError("Unreachable retry loop exit")

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: Any = None,
        data: Any = None,
        product_name: str | None = None,
        token_cache: TokenCache | None = None,
        token_refresher: Callable[[], str] | None = None,
        token_namespace: str = "",
        idempotent: bool | None = None,
        reference_id: str | None = None,
    ) -> httpx.Response:
        """Execute HTTP request with 401 and optional transient retry mapping."""
        validate_request_path(path)
        safe_path = _sanitize_telemetry_path(path)
        effective_ref = (
            reference_id
            or _get_header_ci(headers, "X-Reference-Id")
            or _get_header_ci(headers, "Idempotency-Key")
        )
        logger.debug("%s %s", method, safe_path)
        response, attempts_used = self._send_with_transient_retries(
            method,
            path,
            headers=headers,
            json=json,
            data=data,
            timeout_msg=f"Request timed out: {method} {safe_path}",
            conn_msg=f"Connection error: {method} {safe_path}",
            idempotent=idempotent,
            reference_id=effective_ref,
        )

        if (
            response.status_code == 401
            and token_refresher
            and token_cache
            and product_name
        ):
            # Only invalidate if cache still holds the token that just failed
            failed_token = _extract_bearer_token(headers)
            token_cache.invalidate(
                product_name,
                expected_token=failed_token,
                namespace=token_namespace,
            )

            # Re-fetch a token (preserving upstream 5xx / timeout errors)
            try:
                new_token = token_refresher()
            except (AuthenticationError, ValueError):
                raise AuthenticationError(
                    "Authentication failed during token refresh",
                    reference_id=effective_ref,
                    status_code=401,
                    provider=self._provider_name,
                ) from None
            except PyMomoSDKError as exc:
                if exc.reference_id is None and effective_ref is not None:
                    exc.reference_id = effective_ref
                raise

            # Retry original request once with remaining transient retry budget
            retry_headers = {
                k: v for k, v in headers.items() if k.lower() != "authorization"
            }
            retry_headers["Authorization"] = f"Bearer {new_token}"
            remaining_retries = max(0, self._max_retries - (attempts_used - 1))

            logger.debug("Retrying %s %s with new token", method, safe_path)
            response, _ = self._send_with_transient_retries(
                method,
                path,
                headers=retry_headers,
                json=json,
                data=data,
                timeout_msg=f"Request timed out on retry: {method} {safe_path}",
                conn_msg=f"Connection error on retry: {method} {safe_path}",
                idempotent=idempotent,
                max_retries_override=remaining_retries,
                reference_id=effective_ref,
            )

        _raise_for_status(
            response,
            provider_name=self._provider_name,
            reference_id=effective_ref,
        )
        return response

    def close(self) -> None:
        """Close the underlying client session if owned by this wrapper."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


ModelT = TypeVar("ModelT", bound=BaseModel)


def parse_json_dict(
    response: httpx.Response, *, reference_id: str | None = None
) -> dict[str, Any]:
    """Decode an HTTP response body as a JSON object.

    Raises:
        PyMomoSDKError: If the response body is not valid JSON or not a JSON object.
    """
    try:
        parsed = response.json()
    except ValueError:
        raise PyMomoSDKError(
            "API returned invalid JSON response",
            reference_id=reference_id,
            status_code=response.status_code,
        ) from None
    if not isinstance(parsed, dict):
        raise PyMomoSDKError(
            "API returned unexpected non-object JSON response",
            reference_id=reference_id,
            status_code=response.status_code,
        )
    return parsed


def parse_model(
    response: httpx.Response,
    model_cls: type[ModelT],
    *,
    reference_id: str | None = None,
) -> ModelT:
    """Decode a JSON object response and validate it against a Pydantic model.

    Raises:
        PyMomoSDKError: If the response body is not valid JSON or does not match
            the expected model schema.
    """
    data = parse_json_dict(response, reference_id=reference_id)
    try:
        return model_cls.model_validate(data)
    except ValidationError:
        raise PyMomoSDKError(
            f"API response did not match expected {model_cls.__name__} schema",
            reference_id=reference_id,
            status_code=response.status_code,
        ) from None


def _clean_text(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, int) and type(value) is not bool:
        return str(value)
    return None


def _summarize_validation_details(raw: Any) -> str | None:
    if isinstance(raw, list) and raw:
        items: list[str] = []
        for entry in raw[:5]:
            if isinstance(entry, str) and entry.strip():
                items.append(entry.strip())
            elif isinstance(entry, dict):
                loc = entry.get("loc") or entry.get("field") or entry.get("param")
                msg = (
                    entry.get("msg")
                    or entry.get("message")
                    or entry.get("reason")
                    or entry.get("detail")
                )
                if isinstance(loc, list):
                    loc_str = ".".join(str(p) for p in loc)
                elif isinstance(loc, str):
                    loc_str = loc
                else:
                    loc_str = ""
                if isinstance(msg, str) and msg.strip():
                    items.append(
                        f"{loc_str}: {msg.strip()}" if loc_str else msg.strip()
                    )
        if items:
            return "; ".join(items)
    elif isinstance(raw, dict) and raw:
        parts: list[str] = []
        for k, v in list(raw.items())[:5]:
            if isinstance(v, list) and v:
                parts.append(f"{k}: {', '.join(str(x) for x in v[:3])}")
            elif isinstance(v, str) and v.strip():
                parts.append(f"{k}: {v.strip()}")
        if parts:
            return "; ".join(parts)
    return None


def _extract_error_details(
    response: httpx.Response,
) -> tuple[dict[str, Any], str | None, str | None]:
    """Extract ``(body, error_code, reason)`` across all supported gateway error schemas."""
    body: dict[str, Any] = {}
    parsed_json = False
    try:
        parsed = response.json()
        parsed_json = True
        if isinstance(parsed, dict):
            body = parsed
    except ValueError:
        body = {}

    if not body:
        if parsed_json:
            return {}, None, None
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" in content_type or "application/xhtml" in content_type:
            return {}, None, None
        try:
            raw_text = (response.text or "").strip()
        except Exception:
            raw_text = ""
        if raw_text and not raw_text.lstrip().lower().startswith(
            ("<!doctype", "<html", "<head", "<body")
        ):
            excerpt = raw_text[:240].strip()
            return {}, None, excerpt or None
        return {}, None, None

    error_code: str | None = None
    reason: str | None = None

    # 1. Nested Airtel-style data.transaction.message
    data_obj = body.get("data")
    if isinstance(data_obj, dict):
        tx_obj = data_obj.get("transaction")
        if isinstance(tx_obj, dict):
            reason = _clean_text(tx_obj.get("message")) or reason

    # 2. Nested status object (Airtel)
    status_obj = body.get("status")
    if isinstance(status_obj, dict):
        error_code = (
            _clean_text(status_obj.get("result_code"))
            or _clean_text(status_obj.get("code"))
            or error_code
        )
        reason = _clean_text(status_obj.get("message")) or reason

    # 3. Nested error / reason dict (MTN / OAuth / gateway wrappers)
    for container_key in ("error", "reason"):
        nested = body.get(container_key)
        if isinstance(nested, dict):
            error_code = (
                _clean_text(nested.get("code"))
                or _clean_text(nested.get("errorCode"))
                or error_code
            )
            reason = (
                _clean_text(nested.get("message"))
                or _clean_text(nested.get("description"))
                or _clean_text(nested.get("detail"))
                or reason
            )

    # 4. Top-level error code keys (MTN, Daraja, Wave, Orange, Paystack)
    if error_code is None:
        for code_key in (
            "code",
            "errorCode",
            "result_code",
            "error_code",
            "ResponseCode",
        ):
            val = _clean_text(body.get(code_key))
            if val is not None:
                error_code = val
                break

    # 5. Top-level message / reason keys
    if reason is None:
        for msg_key in (
            "message",
            "errorMessage",
            "error_description",
            "description",
            "ResponseDescription",
            "detail",
            "reason",
        ):
            val = body.get(msg_key)
            if isinstance(val, str) and val.strip():
                reason = val.strip()
                break

    # 6. Structured validation details / errors (Wave details, Paystack/Flutterwave errors)
    details_summary = _summarize_validation_details(
        body.get("details")
    ) or _summarize_validation_details(body.get("errors"))
    if details_summary:
        if reason and details_summary not in reason:
            reason = f"{reason} ({details_summary})"
        elif not reason:
            reason = details_summary

    # 7. OAuth2 top-level string "error" (e.g., Orange {"error": "invalid_client"})
    top_error = body.get("error")
    if isinstance(top_error, str) and top_error.strip():
        if error_code is None and reason is not None:
            error_code = top_error.strip()
        elif reason is None:
            reason = top_error.strip()

    return body, error_code, reason


def _format_error_detail(error_code: str | None, reason: str | None) -> str | None:
    if error_code and reason:
        if error_code in reason:
            return reason
        return f"{error_code}: {reason}"
    return reason or error_code


def _extract_error_message(body: dict[str, Any], default: str) -> str:
    """Extract a human-readable error message from gateway-specific JSON bodies."""
    for key in ("message", "errorMessage", "error_description", "description"):
        raw = body.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw
    return default


def _raise_for_status(
    response: httpx.Response,
    *,
    provider_name: str | None = None,
    reference_id: str | None = None,
) -> None:
    """Map HTTP status codes to structured custom exception classes."""
    status = response.status_code
    if 200 <= status < 300:
        return
    if 300 <= status < 400:
        raise PyMomoSDKError(
            f"Unexpected redirect HTTP status: {status}",
            status_code=status,
            reference_id=reference_id,
            provider=provider_name,
        )

    body, error_code, reason = _extract_error_details(response)
    detail = _format_error_detail(error_code, reason)
    label = provider_name or "Upstream API"

    if status == 400:
        msg = detail or "Bad request"
        raise BadRequestError(
            msg,
            response_body=body,
            reference_id=reference_id,
            status_code=400,
            error_code=error_code,
            reason=reason or msg,
            provider=provider_name,
        )
    if status == 401:
        base = "Invalid or expired credentials"
        msg = f"{base}: {detail}" if detail else base
        raise AuthenticationError(
            msg,
            reference_id=reference_id,
            status_code=401,
            error_code=error_code,
            reason=reason or detail,
            response_body=body,
            provider=provider_name,
        )
    if status == 403:
        base = f"{label} forbidden (HTTP 403)"
        msg = f"{base}: {detail}" if detail else base
        raise PyMomoSDKError(
            msg,
            reference_id=reference_id,
            status_code=403,
            error_code=error_code,
            reason=reason or detail or "Forbidden",
            response_body=body,
            provider=provider_name,
        )
    if status == 404:
        base = "Resource not found"
        msg = f"{base}: {detail}" if detail else base
        raise ResourceNotFoundError(
            msg,
            reference_id=reference_id,
            status_code=404,
            error_code=error_code,
            reason=reason or detail,
            response_body=body,
            provider=provider_name,
        )
    if status == 409:
        conflict_msg = detail or "Conflict: duplicate request reference"
        raise ConflictError(
            conflict_msg,
            reference_id=reference_id,
            status_code=409,
            error_code=error_code,
            reason=reason or conflict_msg,
            response_body=body,
            provider=provider_name,
        )
    if status == 422:
        msg = detail or "Unprocessable entity (HTTP 422)"
        raise BadRequestError(
            msg,
            response_body=body,
            reference_id=reference_id,
            status_code=422,
            error_code=error_code,
            reason=reason or msg,
            provider=provider_name,
        )
    if status == 429:
        base = f"{label} rate limit exceeded (HTTP 429)"
        msg = f"{base}: {detail}" if detail else base
        raise PyMomoSDKError(
            msg,
            reference_id=reference_id,
            status_code=429,
            error_code=error_code,
            reason=reason or detail or "Rate limit exceeded",
            response_body=body,
            provider=provider_name,
        )
    if status >= 500:
        base = f"{label} server error: {status}"
        msg = f"{base} ({detail})" if detail else base
        raise PyMomoSDKServerError(
            msg,
            reference_id=reference_id,
            status_code=status,
            error_code=error_code,
            reason=reason or detail,
            response_body=body,
            provider=provider_name,
        )
    base = f"Unexpected HTTP status: {status}"
    msg = f"{base} ({detail})" if detail else base
    raise PyMomoSDKError(
        msg,
        reference_id=reference_id,
        status_code=status,
        error_code=error_code,
        reason=reason or detail,
        response_body=body,
        provider=provider_name,
    )
