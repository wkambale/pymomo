from __future__ import annotations

import logging
import threading
import time

import httpx

from py_momo_sdk.exceptions import AuthenticationError, PyMomoSDKError
from py_momo_sdk.http import (
    DEFAULT_MAX_RESPONSE_BYTES,
    _extract_error_details,
    _format_error_detail,
)
from py_momo_sdk.utils import validate_base_url, validate_header_value

logger = logging.getLogger("py_momo_sdk.airtel.auth")
_MAX_TOKEN_TTL_SECONDS = 365 * 24 * 60 * 60


def _parse_airtel_token_payload(response: httpx.Response) -> tuple[str, int]:
    """Validate an Airtel OAuth2 token response and return ``(token, expires_in)``."""
    status = response.status_code
    if 300 <= status < 400:
        raise AuthenticationError(
            f"Airtel authentication unexpected redirect: HTTP {status}",
            status_code=status,
            provider="Airtel Money",
        )
    if status == 401:
        body, error_code, reason = _extract_error_details(response)
        detail = _format_error_detail(error_code, reason)
        base = "Invalid or expired Airtel client credentials"
        raise AuthenticationError(
            f"{base}: {detail}" if detail else base,
            status_code=401,
            error_code=error_code,
            reason=reason or detail,
            response_body=body,
            provider="Airtel Money",
        )
    if status >= 400:
        body, error_code, reason = _extract_error_details(response)
        detail = _format_error_detail(error_code, reason)
        base = f"Airtel authentication failed: HTTP {status}"
        raise AuthenticationError(
            f"{base} ({detail})" if detail else base,
            status_code=status,
            error_code=error_code,
            reason=reason or detail,
            response_body=body,
            provider="Airtel Money",
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise AuthenticationError("Airtel OAuth response was not valid JSON") from exc

    if not isinstance(data, dict):
        raise AuthenticationError("Airtel OAuth response did not contain token data")

    token = data.get("access_token")
    expires_in = data.get("expires_in")

    if not isinstance(token, str) or not token.strip() or expires_in is None:
        raise AuthenticationError("Airtel OAuth response did not contain token data")
    try:
        validate_header_value(token, field_name="access_token", allow_whitespace=False)
    except ValueError as exc:
        raise AuthenticationError(
            "Airtel OAuth response contained invalid access_token"
        ) from exc

    if type(expires_in) in (bool, float):
        raise AuthenticationError("Airtel OAuth response had invalid expires_in")
    if isinstance(expires_in, str):
        stripped = expires_in.strip()
        if not stripped.isascii() or not stripped.isdigit() or len(stripped) > 18:
            raise AuthenticationError("Airtel OAuth response had invalid expires_in")
        expires_in_int = int(stripped)
    elif isinstance(expires_in, int):
        expires_in_int = expires_in
    else:
        raise AuthenticationError("Airtel OAuth response had invalid expires_in")
    if expires_in_int <= 0:
        raise AuthenticationError("Airtel OAuth response had invalid expires_in")

    return token, min(expires_in_int, _MAX_TOKEN_TTL_SECONDS)


class AirtelTokenCache:
    """Thread-safe in-memory cache for Airtel access tokens."""

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def get(self) -> str | None:
        """Return a valid cached token or None if absent or expired."""
        with self._lock:
            if self._access_token and time.monotonic() < self._expires_at:
                return self._access_token
            self._access_token = None
            return None

    def set(self, access_token: str, expires_in: int) -> None:
        """Cache a token with a safety margin before expiry (up to 30 seconds)."""
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("access_token must be a non-empty string")
        if (
            type(expires_in) is bool
            or not isinstance(expires_in, int)
            or expires_in <= 0
        ):
            raise ValueError("expires_in must be a positive integer")
        bounded_ttl = min(expires_in, _MAX_TOKEN_TTL_SECONDS)
        margin = min(30.0, bounded_ttl * 0.2)
        expires_at = time.monotonic() + bounded_ttl - margin
        with self._lock:
            self._access_token = access_token
            self._expires_at = expires_at

    def invalidate(self, *, expected_token: str | None = None) -> None:
        """Remove the cached token, forcing the next call to re-authenticate.

        When ``expected_token`` is provided, only invalidates if the cached
        token matches ``expected_token``.
        """
        with self._lock:
            if expected_token is not None and self._access_token != expected_token:
                return
            self._access_token = None
            self._expires_at = 0.0

    def __repr__(self) -> str:
        with self._lock:
            has_token = self._access_token is not None
        return f"AirtelTokenCache(has_token={has_token!r})"

    def __str__(self) -> str:
        return self.__repr__()


def _validate_airtel_auth_params(
    client_id: str,
    client_secret: str,
    base_url: str,
    *,
    max_response_bytes: int,
    allow_localhost: bool,
) -> tuple[str, str, str, int]:
    """Validate AirtelAuth / AsyncAirtelAuth constructor inputs."""
    if not isinstance(client_id, str) or not client_id.strip():
        raise ValueError("client_id must be a non-empty string")
    validate_header_value(client_id, field_name="client_id")
    if not isinstance(client_secret, str) or not client_secret.strip():
        raise ValueError("client_secret must be a non-empty string")
    validate_header_value(client_secret, field_name="client_secret")
    if (
        isinstance(max_response_bytes, bool)
        or not isinstance(max_response_bytes, int)
        or max_response_bytes <= 0
    ):
        raise ValueError("max_response_bytes must be a positive integer")
    validated_url = validate_base_url(base_url, allow_localhost=allow_localhost)
    return client_id, client_secret, validated_url.rstrip("/"), max_response_bytes


class AirtelAuth:
    """Airtel authentication handler."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        allow_localhost: bool = True,
    ) -> None:
        (
            self._client_id,
            self._client_secret,
            self._base_url,
            self._max_response_bytes,
        ) = _validate_airtel_auth_params(
            client_id,
            client_secret,
            base_url,
            max_response_bytes=max_response_bytes,
            allow_localhost=allow_localhost,
        )
        self._cache = AirtelTokenCache()
        self._refresh_lock = threading.Lock()

    def __repr__(self) -> str:
        return (
            f"AirtelAuth(client_id=<redacted>, "
            f"client_secret=<redacted>, base_url={self._base_url!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def get_token(self, client: httpx.Client) -> str:
        """Get a valid access token, fetching a new one if expired."""
        cached = self._cache.get()
        if cached:
            return cached

        with self._refresh_lock:
            cached = self._cache.get()
            if cached:
                return cached
            return self._fetch_token(client)

    def _fetch_token(self, client: httpx.Client) -> str:
        logger.debug("Fetching new Airtel OAuth2 token")
        target = (
            "/auth/oauth2/token"
            if str(client.base_url)
            else f"{self._base_url}/auth/oauth2/token"
        )
        try:
            req = client.build_request(
                "POST",
                target,
                headers={"Content-Type": "application/json"},
                json={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
            )
            response = client.send(req, stream=True, follow_redirects=False)
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
                    if len(buf) + len(chunk) > self._max_response_bytes:
                        raise PyMomoSDKError(
                            f"Response body exceeded maximum allowed size of {self._max_response_bytes} bytes"
                        )
                    buf.extend(chunk)
                response._content = bytes(buf)
            finally:
                response.close()
        except httpx.TimeoutException as exc:
            exc_name = type(exc).__name__
            raise PyMomoSDKError(
                f"Airtel authentication request timed out ({exc_name})",
                reason=exc_name,
                provider="Airtel Money",
            ) from None
        except httpx.RequestError as exc:
            exc_name = type(exc).__name__
            raise PyMomoSDKError(
                f"Airtel authentication request connection error ({exc_name})",
                reason=exc_name,
                provider="Airtel Money",
            ) from None

        token, expires_in_int = _parse_airtel_token_payload(response)
        self._cache.set(token, expires_in_int)
        return token

    def invalidate(self, *, expected_token: str | None = None) -> None:
        """Invalidate the cached token, forcing a refresh on next call."""
        self._cache.invalidate(expected_token=expected_token)
