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


def _extract_airtel_bad_request_message(body: dict[str, Any]) -> str:
    status_obj = body.get("status")
    if isinstance(status_obj, dict):
        nested = status_obj.get("message")
        if isinstance(nested, str) and nested:
            return nested
    top = body.get("message")
    if isinstance(top, str) and top:
        return top
    return "Bad request"


def _raise_for_airtel_status(response: httpx.Response) -> None:
    """Map Airtel HTTP status codes to custom exception classes."""
    if 200 <= response.status_code < 300:
        return
    if 300 <= response.status_code < 400:
        raise PyMomoSDKError(
            f"Unexpected Airtel redirect HTTP status: {response.status_code}"
        )
    body: dict[str, Any] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
    except ValueError:
        body = {}

    if response.status_code == 400:
        raise BadRequestError(
            _extract_airtel_bad_request_message(body), response_body=body
        )
    if response.status_code == 401:
        raise AuthenticationError("Invalid or expired Airtel credentials")
    if response.status_code == 404:
        raise ResourceNotFoundError("Resource not found")
    if response.status_code == 409:
        raise ConflictError("Duplicate transaction reference")
    if response.status_code >= 500:
        raise PyMomoSDKServerError(f"Airtel server error: {response.status_code}")
    raise PyMomoSDKError(f"Unexpected Airtel HTTP status: {response.status_code}")


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
    ) -> httpx.Response:
        can_retry = self._config.max_retries > 0 and _is_retryable_request(
            method, headers
        )
        attempts = (self._config.max_retries + 1) if can_retry else 1
        correlation_id = _get_header_ci(headers, "X-Reference-Id")

        for attempt in range(attempts):
            started = time.monotonic()
            try:
                response = self._execute_bounded(
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
                    time.sleep(
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
                    time.sleep(
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
                time.sleep(delay)
                continue
            return response

        raise PyMomoSDKError(conn_msg)

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """Execute HTTP request with automatic headers, authentication, and retry logic."""
        if not isinstance(method, str) or not method.isascii() or not method.isalpha():
            raise PyMomoSDKError("HTTP method must be a valid ASCII token")
        method = method.upper()
        validate_request_path(path)
        req_headers = _merge_airtel_headers(
            self._config.country, self._config.currency, headers
        )

        token = self._auth.get_token(self._http)
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
        )

        if response.status_code == 401:
            logger.debug("Airtel 401 detected, invalidating cache and retrying")
            self._auth.invalidate(expected_token=token)

            try:
                new_token = self._auth.get_token(self._http)
            except (PyMomoSDKError, ValueError):
                raise AuthenticationError(
                    "Airtel authentication failed during token refresh"
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
            )

        _raise_for_airtel_status(response)
        return response

    def close(self) -> None:
        """Close the underlying HTTP session if owned by this client."""
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
