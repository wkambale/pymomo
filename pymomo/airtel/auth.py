from __future__ import annotations

import logging
import threading
import time

import httpx

from pymomo.exceptions import AuthenticationError, PyMoMoError

logger = logging.getLogger("pymomo.airtel.auth")


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
        """Cache a token with a 30-second safety margin before expiry."""
        expires_at = time.monotonic() + expires_in - 30
        with self._lock:
            self._access_token = access_token
            self._expires_at = expires_at

    def invalidate(self) -> None:
        """Remove the cached token, forcing the next call to re-authenticate."""
        with self._lock:
            self._access_token = None
            self._expires_at = 0.0

    def __repr__(self) -> str:
        with self._lock:
            has_token = self._access_token is not None
        return f"AirtelTokenCache(has_token={has_token!r})"

    def __str__(self) -> str:
        return self.__repr__()


class AirtelAuth:
    """Airtel authentication handler."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url
        self._cache = AirtelTokenCache()

    def __repr__(self) -> str:
        return (
            f"AirtelAuth(client_id={self._client_id!r}, "
            f"client_secret=<redacted>, base_url={self._base_url!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def get_token(self, client: httpx.Client) -> str:
        """Get a valid access token, fetching a new one if expired."""
        cached = self._cache.get()
        if cached:
            return cached

        logger.debug("Fetching new Airtel OAuth2 token")
        try:
            response = client.request(
                "POST",
                "/auth/oauth2/token",
                headers={"Content-Type": "application/json"},
                json={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
            )
        except httpx.TimeoutException:
            raise PyMoMoError("Airtel authentication request timed out") from None
        except httpx.RequestError:
            raise PyMoMoError(
                "Airtel authentication request connection error"
            ) from None

        if response.status_code == 401:
            raise AuthenticationError("Invalid or expired Airtel client credentials")
        if response.status_code >= 400:
            raise AuthenticationError(
                f"Airtel authentication failed: HTTP {response.status_code}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AuthenticationError(
                "Airtel OAuth response was not valid JSON"
            ) from exc

        if not isinstance(data, dict):
            raise AuthenticationError(
                "Airtel OAuth response did not contain token data"
            )

        token = data.get("access_token")
        expires_in = data.get("expires_in")

        if not isinstance(token, str) or not token or expires_in is None:
            raise AuthenticationError(
                "Airtel OAuth response did not contain token data"
            )
        if isinstance(expires_in, bool):
            raise AuthenticationError("Airtel OAuth response had invalid expires_in")
        try:
            expires_in_int = int(expires_in)
        except (TypeError, ValueError) as exc:
            raise AuthenticationError(
                "Airtel OAuth response had invalid expires_in"
            ) from exc
        if expires_in_int <= 0:
            raise AuthenticationError("Airtel OAuth response had invalid expires_in")

        self._cache.set(token, expires_in_int)
        return token

    def invalidate(self) -> None:
        """Invalidate the cached token, forcing a refresh on next call."""
        self._cache.invalidate()
