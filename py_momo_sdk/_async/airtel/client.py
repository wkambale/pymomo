from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

from py_momo_sdk._async.airtel.auth import AsyncAirtelAuth
from py_momo_sdk._async.airtel.products.collection import AsyncAirtelCollection
from py_momo_sdk._async.airtel.products.disbursement import AsyncAirtelDisbursement
from py_momo_sdk.airtel.client import _merge_airtel_headers, _raise_for_airtel_status
from py_momo_sdk.airtel.config import AirtelConfig
from py_momo_sdk.exceptions import AuthenticationError, PyMomoSDKError
from py_momo_sdk.http import (
    _RETRYABLE_STATUS_CODES,
    DEFAULT_MAX_RESPONSE_BYTES,
    _compute_retry_delay,
    _get_header_ci,
    _is_retryable_request,
    _ResponseTooLargeError,
    _sanitize_telemetry_path,
)
from py_momo_sdk.telemetry import RequestTelemetryEvent, TelemetryHook
from py_momo_sdk.utils import (
    validate_base_url,
    validate_matching_origin,
    validate_request_path,
)

if TYPE_CHECKING:
    from typing_extensions import Self

logger = logging.getLogger("py_momo_sdk.airtel.client")


class AsyncAirtelClient:
    """Asynchronous Airtel Money API client."""

    def __init__(
        self,
        config: AirtelConfig,
        *,
        client: httpx.AsyncClient | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        telemetry: TelemetryHook | None = None,
    ) -> None:
        self._config = config
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes <= 0
        ):
            raise ValueError("max_response_bytes must be a positive integer")
        base_url = validate_base_url(self._config.base_url or "")
        self._validated_base_url = base_url.rstrip("/")
        self._max_response_bytes = max_response_bytes
        self._telemetry = telemetry if telemetry is not None else config.telemetry
        self._owns_client = client is None

        self._auth = AsyncAirtelAuth(
            client_id=config.client_id,
            client_secret=config.client_secret,
            base_url=base_url,
            max_response_bytes=max_response_bytes,
        )
        if client is not None:
            injected_base = str(client.base_url)
            if injected_base:
                validate_base_url(injected_base)
                validate_matching_origin(base_url, injected_base)
            self._http = client
        else:
            self._http = httpx.AsyncClient(
                base_url=base_url,
                timeout=config.timeout,
                follow_redirects=False,
            )
        self._collection: AsyncAirtelCollection | None = None
        self._disbursement: AsyncAirtelDisbursement | None = None

    @property
    def collection(self) -> AsyncAirtelCollection:
        """Get async Airtel Collection product client instance."""
        if self._collection is None:
            self._collection = AsyncAirtelCollection(client=self)
        return self._collection

    @property
    def disbursement(self) -> AsyncAirtelDisbursement:
        """Get async Airtel Disbursement product client instance."""
        if self._disbursement is None:
            self._disbursement = AsyncAirtelDisbursement(client=self)
        return self._disbursement

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

    async def _execute_bounded(
        self, method: str, path: str, *, headers: dict[str, str], json: Any
    ) -> httpx.Response:
        target = (
            path if str(self._http.base_url) else f"{self._validated_base_url}{path}"
        )
        req = self._http.build_request(method, target, headers=headers, json=json)
        response = await self._http.send(req, stream=True, follow_redirects=False)
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

    async def _send_with_retries(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: Any,
        timeout_msg: str,
        conn_msg: str,
    ) -> httpx.Response:
        can_retry = self._config.max_retries > 0 and _is_retryable_request(
            method, headers
        )
        attempts = (self._config.max_retries + 1) if can_retry else 1
        correlation_id = _get_header_ci(headers, "X-Reference-Id")

        for attempt in range(attempts):
            started = time.monotonic()
            try:
                response = await self._execute_bounded(
                    method, path, headers=headers, json=json
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
                        _compute_retry_delay(attempt, self._config.retry_backoff, None)
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
                        _compute_retry_delay(attempt, self._config.retry_backoff, None)
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
                delay = _compute_retry_delay(
                    attempt, self._config.retry_backoff, response
                )
                await asyncio.sleep(delay)
                continue
            return response

        raise PyMomoSDKError(conn_msg)

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """Execute async HTTP request with automatic headers, auth, and 401 retry."""
        if not isinstance(method, str) or not method.isascii() or not method.isalpha():
            raise PyMomoSDKError("HTTP method must be a valid ASCII token")
        method = method.upper()
        validate_request_path(path)
        req_headers = _merge_airtel_headers(
            self._config.country, self._config.currency, headers
        )

        token = await self._auth.get_token(self._http)
        req_headers["Authorization"] = f"Bearer {token}"

        safe_path = _sanitize_telemetry_path(path)
        logger.debug("%s %s", method, safe_path)

        response = await self._send_with_retries(
            method,
            path,
            headers=req_headers,
            json=json,
            timeout_msg=f"Airtel request timed out: {method} {safe_path}",
            conn_msg=f"Airtel connection error: {method} {safe_path}",
        )

        if response.status_code == 401:
            logger.debug("Airtel 401 detected, invalidating cache and retrying")
            self._auth.invalidate(expected_token=token)
            try:
                new_token = await self._auth.get_token(self._http)
            except (PyMomoSDKError, ValueError):
                raise AuthenticationError(
                    "Airtel authentication failed during token refresh"
                ) from None

            retry_headers = req_headers.copy()
            retry_headers["Authorization"] = f"Bearer {new_token}"
            logger.debug("Retrying Airtel %s %s with new token", method, safe_path)
            response = await self._send_with_retries(
                method,
                path,
                headers=retry_headers,
                json=json,
                timeout_msg=f"Airtel request timed out on retry: {method} {safe_path}",
                conn_msg=f"Airtel connection error on retry: {method} {safe_path}",
            )

        _raise_for_airtel_status(response)
        return response

    async def close(self) -> None:
        """Close the underlying async HTTP session if owned by this client."""
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
