from __future__ import annotations

import logging
import re
import secrets
import time
from collections.abc import Callable, Mapping
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


def _get_header_ci(headers: Mapping[str, str], name: str) -> str | None:
    target = name.lower()
    for k, v in headers.items():
        if k.lower() == target:
            return v
    return None


def _sanitize_telemetry_path(path: str) -> str:
    raw_path = path.split("?", 1)[0]
    return _ACCOUNTHOLDER_PATH_RE.sub(r"\1<redacted>", raw_path)


def _is_retryable_request(method: str, headers: dict[str, str]) -> bool:
    if method.upper() in _IDEMPOTENT_METHODS:
        return True
    ref_val = _get_header_ci(headers, "X-Reference-Id")
    return bool(ref_val and ref_val.strip())


def _compute_retry_delay(
    attempt: int, base_backoff: float, response: httpx.Response | None
) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                parsed = float(retry_after)
                if 0 < parsed <= 30.0:
                    return parsed
            except ValueError:
                pass
    jitter = secrets.randbelow(250) / 1000.0
    exp = min(max(attempt, 0), 30)
    return float(min(base_backoff * (2**exp) + jitter, 30.0))


class HttpClient:
    """Thin wrapper around httpx.Client with retry logic and error mappings."""

    def __init__(
        self,
        base_url: str,
        timeout: float,
        *,
        max_retries: int = 0,
        retry_backoff: float = 0.5,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        client: httpx.Client | None = None,
        telemetry: TelemetryHook | None = None,
    ) -> None:
        validated_url = validate_base_url(base_url)
        validated_timeout = validate_timeout(timeout)
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
        self._owns_client = client is None
        if client is not None:
            injected_base = str(client.base_url)
            if injected_base:
                validate_base_url(injected_base)
            self._client = client
        else:
            self._client = httpx.Client(
                base_url=validated_url,
                timeout=validated_timeout,
                follow_redirects=False,
            )

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
        if "request" in self._client.__dict__:
            response = self._client.request(
                method,
                target,
                headers=headers,
                json=json,
                data=data,
                follow_redirects=False,
            )
            if len(response.content) > self._max_response_bytes:
                raise PyMomoSDKError(
                    f"Response body exceeded maximum allowed size of {self._max_response_bytes} bytes"
                )
            return response

        req = self._client.build_request(
            method, target, headers=headers, json=json, data=data
        )
        response = self._client.send(req, stream=True, follow_redirects=False)
        try:
            cl_header = response.headers.get("Content-Length")
            if cl_header is not None:
                try:
                    if int(cl_header) > self._max_response_bytes:
                        raise PyMomoSDKError(
                            f"Response body exceeded maximum allowed size of {self._max_response_bytes} bytes"
                        )
                except ValueError:
                    pass
            buf = bytearray()
            for chunk in response.iter_bytes():
                buf.extend(chunk)
                if len(buf) > self._max_response_bytes:
                    raise PyMomoSDKError(
                        f"Response body exceeded maximum allowed size of {self._max_response_bytes} bytes"
                    )
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
    ) -> httpx.Response:
        can_retry = self._max_retries > 0 and _is_retryable_request(method, headers)
        attempts = (self._max_retries + 1) if can_retry else 1
        correlation_id = _get_header_ci(headers, "X-Reference-Id")

        for attempt in range(attempts):
            started = time.monotonic()
            try:
                response = self._execute_bounded_request(
                    method, path, headers=headers, json=json, data=data
                )
            except httpx.TimeoutException:
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
                raise PyMomoSDKError(timeout_msg) from None
            except httpx.RequestError:
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
                raise PyMomoSDKError(conn_msg) from None

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
            return response

        raise PyMomoSDKError(conn_msg)

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
    ) -> httpx.Response:
        """Execute HTTP request with 401 and optional transient retry mapping."""
        validate_request_path(path)
        safe_path = _sanitize_telemetry_path(path)
        logger.debug("%s %s", method, safe_path)
        response = self._send_with_transient_retries(
            method,
            path,
            headers=headers,
            json=json,
            data=data,
            timeout_msg=f"Request timed out: {method} {safe_path}",
            conn_msg=f"Connection error: {method} {safe_path}",
        )

        if (
            response.status_code == 401
            and token_refresher
            and token_cache
            and product_name
        ):
            # Only invalidate if cache still holds the token that just failed
            auth_val = _get_header_ci(headers, "Authorization") or ""
            failed_token = auth_val[7:] if auth_val.startswith("Bearer ") else None
            token_cache.invalidate(product_name, expected_token=failed_token)

            # Re-fetch a token
            try:
                new_token = token_refresher()
            except (PyMomoSDKError, ValueError):
                raise AuthenticationError(
                    "Authentication failed during token refresh"
                ) from None

            # Retry original request exactly once
            retry_headers = {
                k: v for k, v in headers.items() if k.lower() != "authorization"
            }
            retry_headers["Authorization"] = f"Bearer {new_token}"

            logger.debug("Retrying %s %s with new token", method, safe_path)
            response = self._send_with_transient_retries(
                method,
                path,
                headers=retry_headers,
                json=json,
                data=data,
                timeout_msg=f"Request timed out on retry: {method} {safe_path}",
                conn_msg=f"Connection error on retry: {method} {safe_path}",
            )

        _raise_for_status(response)
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


def parse_json_dict(response: httpx.Response) -> dict[str, Any]:
    """Decode an HTTP response body as a JSON object.

    Raises:
        PyMomoSDKError: If the response body is not valid JSON or not a JSON object.
    """
    try:
        parsed = response.json()
    except ValueError:
        raise PyMomoSDKError("API returned invalid JSON response") from None
    if not isinstance(parsed, dict):
        raise PyMomoSDKError("API returned unexpected non-object JSON response")
    return parsed


def parse_model(response: httpx.Response, model_cls: type[ModelT]) -> ModelT:
    """Decode a JSON object response and validate it against a Pydantic model.

    Raises:
        PyMomoSDKError: If the response body is not valid JSON or does not match
            the expected model schema.
    """
    data = parse_json_dict(response)
    try:
        return model_cls.model_validate(data)
    except ValidationError:
        raise PyMomoSDKError(
            f"API response did not match expected {model_cls.__name__} schema"
        ) from None


def _raise_for_status(response: httpx.Response) -> None:
    """Map HTTP status codes to custom exception classes."""
    if 200 <= response.status_code < 300:
        return
    if 300 <= response.status_code < 400:
        raise PyMomoSDKError(f"Unexpected redirect HTTP status: {response.status_code}")
    body: dict[str, Any] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
    except ValueError:
        body = {}

    if response.status_code == 400:
        raw_msg = body.get("message")
        msg = raw_msg if isinstance(raw_msg, str) and raw_msg else "Bad request"
        raise BadRequestError(msg, response_body=body)
    if response.status_code == 401:
        raise AuthenticationError("Invalid or expired credentials")
    if response.status_code == 404:
        raise ResourceNotFoundError("Resource not found")
    if response.status_code == 409:
        raise ConflictError("Duplicate X-Reference-Id")
    if response.status_code >= 500:
        raise PyMomoSDKServerError(f"MTN server error: {response.status_code}")
    raise PyMomoSDKError(f"Unexpected HTTP status: {response.status_code}")
