from __future__ import annotations

import logging
import time

import httpx

from pymomo.exceptions import AuthenticationError, PyMoMoError

logger = logging.getLogger("pymomo.airtel.auth")


class AirtelTokenCache:
    """Thread-safe in-memory cache for Airtel access tokens."""

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    def get(self) -> str | None:
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token
        self._access_token = None
        return None

    def set(self, access_token: str, expires_in: int) -> None:
        # Subtract 30-second safety margin
        self._expires_at = time.monotonic() + expires_in - 30
        self._access_token = access_token

    def invalidate(self) -> None:
        self._access_token = None
        self._expires_at = 0.0


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
        except httpx.TimeoutException as exc:
            raise PyMoMoError("Airtel authentication request timed out") from exc
        except httpx.RequestError as exc:
            raise PyMoMoError("Airtel authentication request connection error") from exc

        if response.status_code == 401:
            raise AuthenticationError("Invalid or expired Airtel client credentials")
        if response.status_code >= 400:
            raise AuthenticationError(
                f"Airtel authentication failed: HTTP {response.status_code}"
            )

        data = response.json()
        token = data.get("access_token")
        expires_in = data.get("expires_in")

        if not isinstance(token, str) or expires_in is None:
            raise AuthenticationError(
                "Airtel OAuth response did not contain token data"
            )

        self._cache.set(token, int(expires_in))
        return token

    def invalidate(self) -> None:
        """Invalidate the cached token, forcing a refresh on next call."""
        self._cache.invalidate()
