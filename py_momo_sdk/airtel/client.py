from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx

from py_momo_sdk.airtel.auth import AirtelAuth
from py_momo_sdk.airtel.config import AirtelConfig
from py_momo_sdk.airtel.products.collection import Collection
from py_momo_sdk.airtel.products.disbursement import Disbursement
from py_momo_sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    PyMomoSDKError,
    PyMomoSDKServerError,
    ResourceNotFoundError,
)
from py_momo_sdk.http import (
    _RETRYABLE_STATUS_CODES,
    DEFAULT_MAX_RESPONSE_BYTES,
    _compute_retry_delay,
    _extract_error_details,
    _format_error_detail,
    _get_header_ci,
    _is_retryable_request,
    _ResponseTooLargeError,
    _sanitize_telemetry_path,
)
from py_momo_sdk.telemetry import RequestTelemetryEvent, TelemetryHook
from py_momo_sdk.utils import (
    validate_base_url,
    validate_header_value,
    validate_matching_origin,
    validate_request_path,
)

if TYPE_CHECKING:
    from typing_extensions import Self

logger = logging.getLogger("py_momo_sdk.airtel.client")


def _merge_airtel_headers(
    country: str, currency: str, extra: dict[str, str] | None
) -> dict[str, str]:
    req_headers: dict[str, str] = {
        "X-Country": country,
        "X-Currency": currency,
        "Content-Type": "application/json",
    }
    if extra:
        for key, value in extra.items():
            if (
                not isinstance(key, str)
                or not key
                or any(ch.isspace() or ch == ":" for ch in key)
            ):
                raise PyMomoSDKError("HTTP header name is invalid")
            try:
                validate_header_value(key, field_name="header name")
                validate_header_value(value, field_name=key)
            except ValueError as exc:
                raise PyMomoSDKError(str(exc)) from None
            key_lower = key.lower()
            if key_lower == "authorization":
                continue
            existing = [k for k in req_headers if k.lower() == key_lower]
            for k in existing:
                del req_headers[k]
            req_headers[key] = value
    return req_headers


def _raise_for_airtel_status(
    response: httpx.Response, *, reference_id: str | None = None
) -> None:
    """Map Airtel HTTP status codes to structured custom exception classes."""
    status = response.status_code
    if 200 <= status < 300:
        return
    if 300 <= status < 400:
        raise PyMomoSDKError(
            f"Unexpected Airtel redirect HTTP status: {status}",
            status_code=status,
            reference_id=reference_id,
            provider="Airtel Money",
        )

    body, error_code, reason = _extract_error_details(response)
    detail = _format_error_detail(error_code, reason)

    if status == 400:
        msg = detail or "Bad request"
        raise BadRequestError(
            msg,
            response_body=body,
            reference_id=reference_id,
            status_code=400,
            error_code=error_code,
            reason=reason or msg,
            provider="Airtel Money",
        )
    if status == 401:
        base = "Invalid or expired Airtel credentials"
        msg = f"{base}: {detail}" if detail else base
        raise AuthenticationError(
            msg,
            reference_id=reference_id,
            status_code=401,
            error_code=error_code,
            reason=reason or detail,
            response_body=body,
            provider="Airtel Money",
        )
    if status == 403:
        base = "Airtel Money forbidden (HTTP 403)"
        msg = f"{base}: {detail}" if detail else base
        raise PyMomoSDKError(
            msg,
            reference_id=reference_id,
            status_code=403,
            error_code=error_code,
            reason=reason or detail or "Forbidden",
            response_body=body,
            provider="Airtel Money",
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
            provider="Airtel Money",
        )
    if status == 409:
        msg = detail or "Duplicate transaction reference"
        raise ConflictError(
            msg,
            reference_id=reference_id,
            status_code=409,
            error_code=error_code,
            reason=reason or msg,
            response_body=body,
            provider="Airtel Money",
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
            provider="Airtel Money",
        )
    if status == 429:
        base = "Airtel Money rate limit exceeded (HTTP 429)"
        msg = f"{base}: {detail}" if detail else base
        raise PyMomoSDKError(
            msg,
            reference_id=reference_id,
            status_code=429,
            error_code=error_code,
            reason=reason or detail or "Rate limit exceeded",
            response_body=body,
            provider="Airtel Money",
        )
    if status >= 500:
        base = f"Airtel server error: {status}"
        msg = f"{base} ({detail})" if detail else base
        raise PyMomoSDKServerError(
            msg,
            reference_id=reference_id,
            status_code=status,
            error_code=error_code,
            reason=reason or detail,
            response_body=body,
            provider="Airtel Money",
        )
    base = f"Unexpected Airtel HTTP status: {status}"
    msg = f"{base} ({detail})" if detail else base
    raise PyMomoSDKError(
        msg,
        reference_id=reference_id,
        status_code=status,
        error_code=error_code,
        reason=reason or detail,
        response_body=body,
        provider="Airtel Money",
    )


class AirtelClient:
    """Synchronous Airtel Money API client."""

    def __init__(
        self,
        config: AirtelConfig,
        *,
        client: httpx.Client | None = None,
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
        self._lock = threading.Lock()

        self._auth = AirtelAuth(
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
            self._http = httpx.Client(
                base_url=base_url,
                timeout=config.timeout,
                follow_redirects=False,
            )

        self._collection: Collection | None = None
        self._disbursement: Disbursement | None = None

    @property
    def collection(self) -> Collection:
        """Get Airtel Collection product client instance."""
        if self._collection is None:
            with self._lock:
                if self._collection is None:
                    self._collection = Collection(client=self)
        return self._collection

    @property
    def disbursement(self) -> Disbursement:
        """Get Airtel Disbursement product client instance."""
        if self._disbursement is None:
            with self._lock:
                if self._disbursement is None:
                    self._disbursement = Disbursement(client=self)
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

    def _execute_bounded(
        self, method: str, path: str, *, headers: dict[str, str], json: Any
    ) -> httpx.Response:
        target = (
            path if str(self._http.base_url) else f"{self._validated_base_url}{path}"
        )
        req = self._http.build_request(method, target, headers=headers, json=json)
        response = self._http.send(req, stream=True, follow_redirects=False)
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

    def _send_with_retries(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: Any,
        timeout_msg: str,
        conn_msg: str,
        reference_id: str | None = None,
    ) -> httpx.Response:
        can_retry = self._config.max_retries > 0 and _is_retryable_request(
            method, headers
        )
        attempts = (self._config.max_retries + 1) if can_retry else 1
        correlation_id = reference_id or _get_header_ci(headers, "X-Reference-Id")

        for attempt in range(attempts):
            started = time.monotonic()
            try:
                response = self._execute_bounded(
                    method, path, headers=headers, json=json
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
                if exc.provider is None:
                    exc.provider = "Airtel Money"
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
                    time.sleep(
                        _compute_retry_delay(attempt, self._config.retry_backoff, None)
                    )
                    continue
                raise PyMomoSDKError(
                    f"{timeout_msg} ({exc_name})",
                    reference_id=correlation_id,
                    reason=exc_name,
                    provider="Airtel Money",
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
                    time.sleep(
                        _compute_retry_delay(attempt, self._config.retry_backoff, None)
                    )
                    continue
                raise PyMomoSDKError(
                    f"{conn_msg} ({exc_name})",
                    reference_id=correlation_id,
                    reason=exc_name,
                    provider="Airtel Money",
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
                delay = _compute_retry_delay(
                    attempt, self._config.retry_backoff, response
                )
                time.sleep(delay)
                continue
            return response

        raise PyMomoSDKError(
            conn_msg, reference_id=correlation_id, provider="Airtel Money"
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        reference_id: str | None = None,
    ) -> httpx.Response:
        """Execute HTTP request with automatic headers, authentication, and retry logic."""
        if not isinstance(method, str) or not method.isascii() or not method.isalpha():
            raise PyMomoSDKError(
                "HTTP method must be a valid ASCII token",
                reference_id=reference_id,
                provider="Airtel Money",
            )
        method = method.upper()
        validate_request_path(path)
        req_headers = _merge_airtel_headers(
            self._config.country, self._config.currency, headers
        )
        effective_ref = reference_id or _get_header_ci(req_headers, "X-Reference-Id")

        try:
            token = self._auth.get_token(self._http)
        except PyMomoSDKError as exc:
            if exc.reference_id is None and effective_ref is not None:
                exc.reference_id = effective_ref
            raise
        req_headers["Authorization"] = f"Bearer {token}"

        safe_path = _sanitize_telemetry_path(path)
        logger.debug("%s %s", method, safe_path)

        response = self._send_with_retries(
            method,
            path,
            headers=req_headers,
            json=json,
            timeout_msg=f"Airtel request timed out: {method} {safe_path}",
            conn_msg=f"Airtel connection error: {method} {safe_path}",
            reference_id=effective_ref,
        )

        if response.status_code == 401:
            logger.debug("Airtel 401 detected, invalidating cache and retrying")
            self._auth.invalidate(expected_token=token)

            try:
                new_token = self._auth.get_token(self._http)
            except (PyMomoSDKError, ValueError):
                raise AuthenticationError(
                    "Airtel authentication failed during token refresh",
                    reference_id=effective_ref,
                    status_code=401,
                    provider="Airtel Money",
                ) from None

            retry_headers = req_headers.copy()
            retry_headers["Authorization"] = f"Bearer {new_token}"

            logger.debug("Retrying Airtel %s %s with new token", method, safe_path)
            response = self._send_with_retries(
                method,
                path,
                headers=retry_headers,
                json=json,
                timeout_msg=f"Airtel request timed out on retry: {method} {safe_path}",
                conn_msg=f"Airtel connection error on retry: {method} {safe_path}",
                reference_id=effective_ref,
            )

        _raise_for_airtel_status(response, reference_id=effective_ref)
        return response

    def close(self) -> None:
        """Close the underlying HTTP session if owned by this client."""
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
