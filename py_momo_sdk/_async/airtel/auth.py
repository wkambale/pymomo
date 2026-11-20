from __future__ import annotations

import asyncio
import logging

import httpx

from py_momo_sdk.airtel.auth import AirtelTokenCache
from py_momo_sdk.exceptions import AuthenticationError, PyMomoSDKError

logger = logging.getLogger("py_momo_sdk.airtel.auth")


class AsyncAirtelAuth:
    """Asynchronous Airtel authentication handler."""

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
        self._refresh_lock: asyncio.Lock | None = None

    def __repr__(self) -> str:
        return (
            f"AsyncAirtelAuth(client_id={self._client_id!r}, "
            f"client_secret=<redacted>, base_url={self._base_url!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def _get_lock(self) -> asyncio.Lock:
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        return self._refresh_lock

    async def get_token(self, client: httpx.AsyncClient) -> str:
        """Get a valid access token asynchronously, fetching a new one if expired."""
        cached = self._cache.get()
        if cached:
            return cached

        async with self._get_lock():
            cached = self._cache.get()
            if cached:
                return cached
            return await self._fetch_token(client)

    async def _fetch_token(self, client: httpx.AsyncClient) -> str:
        logger.debug("Fetching new async Airtel OAuth2 token")
        try:
            response = await client.request(
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
            raise PyMomoSDKError("Airtel authentication request timed out") from None
        except httpx.RequestError:
            raise PyMomoSDKError(
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

    def invalidate(self, *, expected_token: str | None = None) -> None:
        """Invalidate the cached token, forcing a refresh on next call."""
        self._cache.invalidate(expected_token=expected_token)
