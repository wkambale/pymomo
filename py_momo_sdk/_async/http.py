from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import httpx

from py_momo_sdk.auth import TokenCache
from py_momo_sdk.exceptions import (
    AuthenticationError,
    PyMomoSDKError,
)
from py_momo_sdk.http import (
    _RETRYABLE_STATUS_CODES,
    DEFAULT_MAX_RESPONSE_BYTES,
    _compute_retry_delay,
    _extract_bearer_token,
    _get_header_ci,
    _is_retryable_request,
    _raise_for_status,
    _ResponseTooLargeError,
    _sanitize_telemetry_path,
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


class AsyncHttpClient:
    """Thin wrapper around httpx.AsyncClient with retry logic and error mappings."""

    def __init__(
        self,
        base_url: str,
        timeout: float | httpx.Timeout,
        *,
        max_retries: int = 0,
        retry_backoff: float = 0.5,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        client: httpx.AsyncClient | None = None,
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
            self._client = httpx.AsyncClient(**client_kwargs)

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

    async def _execute_bounded_request(
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
        response = await self._client.send(req, stream=True, follow_redirects=False)
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
            async for chunk in response.aiter_bytes():
                if len(buf) + len(chunk) > self._max_response_bytes:
                    raise _ResponseTooLargeError(
                        f"Response body exceeded maximum allowed size of {self._max_response_bytes} bytes"
                    )
                buf.extend(chunk)
            response._content = bytes(buf)
        finally:
            await response.aclose()
        return response

    async def _send_with_transient_retries(
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
    ) -> tuple[httpx.Response, int]:
        effective_retries = (
            self._max_retries if max_retries_override is None else max_retries_override
        )
        can_retry = effective_retries > 0 and _is_retryable_request(
            method, headers, idempotent=idempotent
        )
        attempts = (effective_retries + 1) if can_retry else 1
        correlation_id = _get_header_ci(headers, "X-Reference-Id") or _get_header_ci(
            headers, "Idempotency-Key"
        )

        for attempt in range(attempts):
            started = time.monotonic()
            try:
                response = await self._execute_bounded_request(
                    method, path, headers=headers, json=json, data=data
                )
            except _ResponseTooLargeError:
                self._emit_telemetry(
                    method,
                    path,
                    None,
                    started,
                    attempt + 1,
                    correlation_id,
                    "ResponseTooLargeError",
                )
                raise
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
                    await asyncio.sleep(
                        _compute_retry_delay(attempt, self._retry_backoff, None)
                    )
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
                    await asyncio.sleep(
                        _compute_retry_delay(attempt, self._retry_backoff, None)
                    )
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
                await asyncio.sleep(delay)
                continue
            return response, attempt + 1

        raise AssertionError("Unreachable retry loop exit")

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: Any = None,
        data: Any = None,
        product_name: str | None = None,
        token_cache: TokenCache | None = None,
        token_refresher: Callable[[], Coroutine[Any, Any, str]] | None = None,
        token_namespace: str = "",
        idempotent: bool | None = None,
    ) -> httpx.Response:
        """Execute async HTTP request with 401 and optional transient retry mapping."""
        validate_request_path(path)
        safe_path = _sanitize_telemetry_path(path)
        logger.debug("%s %s", method, safe_path)
        response, attempts_used = await self._send_with_transient_retries(
            method,
            path,
            headers=headers,
            json=json,
            data=data,
            timeout_msg=f"Request timed out: {method} {safe_path}",
            conn_msg=f"Connection error: {method} {safe_path}",
            idempotent=idempotent,
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

            # Re-fetch a token asynchronously (preserving upstream 5xx / timeout errors)
            try:
                new_token = await token_refresher()
            except (AuthenticationError, ValueError):
                raise AuthenticationError(
                    "Authentication failed during token refresh"
                ) from None

            # Retry original request once with remaining transient retry budget
            retry_headers = {
                k: v for k, v in headers.items() if k.lower() != "authorization"
            }
            retry_headers["Authorization"] = f"Bearer {new_token}"
            remaining_retries = max(0, self._max_retries - (attempts_used - 1))

            logger.debug("Retrying %s %s with new token", method, safe_path)
            response, _ = await self._send_with_transient_retries(
                method,
                path,
                headers=retry_headers,
                json=json,
                data=data,
                timeout_msg=f"Request timed out on retry: {method} {safe_path}",
                conn_msg=f"Connection error on retry: {method} {safe_path}",
                idempotent=idempotent,
                max_retries_override=remaining_retries,
            )

        ref_id = _get_header_ci(headers, "X-Reference-Id") or _get_header_ci(
            headers, "Idempotency-Key"
        )
        _raise_for_status(
            response,
            provider_name=self._provider_name,
            reference_id=ref_id,
        )
        return response

    async def close(self) -> None:
        """Close the underlying client session if owned by this wrapper."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
