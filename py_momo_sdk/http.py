from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Callable
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
from py_momo_sdk.utils import validate_base_url, validate_request_path

if TYPE_CHECKING:
    from typing_extensions import Self

logger = logging.getLogger("py_momo_sdk.http")

_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _is_retryable_request(method: str, headers: dict[str, str]) -> bool:
    if method.upper() in _IDEMPOTENT_METHODS:
        return True
    return any(k.lower() == "x-reference-id" for k in headers)


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
    return float(min(base_backoff * (2**attempt) + jitter, 30.0))


class HttpClient:
    """Thin wrapper around httpx.Client with retry logic and error mappings."""

    def __init__(
        self,
        base_url: str,
        timeout: float,
        *,
        max_retries: int = 0,
        retry_backoff: float = 0.5,
        client: httpx.Client | None = None,
        telemetry: TelemetryHook | None = None,
    ) -> None:
        validated_url = validate_base_url(base_url)
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._telemetry = telemetry
        self._client = client or httpx.Client(
            base_url=validated_url,
            timeout=timeout,
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
        self._telemetry.on_request(
            RequestTelemetryEvent(
                method=method,
                path=path,
                status_code=status_code,
                latency_ms=(time.monotonic() - started) * 1000.0,
                attempt=attempt,
                correlation_id=correlation_id,
                error_type=error_type,
            )
        )

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
        correlation_id = headers.get("X-Reference-Id")

        for attempt in range(attempts):
            started = time.monotonic()
            try:
                response = self._client.request(
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
                    path,
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
        logger.debug("%s %s", method, path)
        response = self._send_with_transient_retries(
            method,
            path,
            headers=headers,
            json=json,
            data=data,
            timeout_msg=f"Request timed out: {method} {path}",
            conn_msg=f"Connection error: {method} {path}",
        )

        if (
            response.status_code == 401
            and token_refresher
            and token_cache
            and product_name
        ):
            # Only invalidate if cache still holds the token that just failed
            auth_val = headers.get("Authorization", "")
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
            retry_headers = headers.copy()
            retry_headers["Authorization"] = f"Bearer {new_token}"

            logger.debug("Retrying %s %s with new token", method, path)
            response = self._send_with_transient_retries(
                method,
                path,
                headers=retry_headers,
                json=json,
                data=data,
                timeout_msg=f"Request timed out on retry: {method} {path}",
                conn_msg=f"Connection error on retry: {method} {path}",
            )

        _raise_for_status(response)
        return response

    def close(self) -> None:
        """Close the underlying client session."""
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
    if response.status_code < 400:
        return
    body: dict[str, Any] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
    except ValueError:
        body = {}

    if response.status_code == 400:
        raise BadRequestError(body.get("message", "Bad request"), response_body=body)
    if response.status_code == 401:
        raise AuthenticationError("Invalid or expired credentials")
    if response.status_code == 404:
        raise ResourceNotFoundError("Resource not found")
    if response.status_code == 409:
        raise ConflictError("Duplicate X-Reference-Id")
    if response.status_code >= 500:
        raise PyMomoSDKServerError(f"MTN server error: {response.status_code}")
    raise PyMomoSDKError(f"Unexpected HTTP status: {response.status_code}")
