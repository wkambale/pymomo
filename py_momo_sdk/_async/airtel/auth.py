from __future__ import annotations

import asyncio
import logging
import threading
import weakref

import httpx

from py_momo_sdk.airtel.auth import AirtelTokenCache, _parse_airtel_token_payload
from py_momo_sdk.exceptions import PyMomoSDKError
from py_momo_sdk.http import DEFAULT_MAX_RESPONSE_BYTES

logger = logging.getLogger("py_momo_sdk.airtel.auth")


class AsyncAirtelAuth:
    """Asynchronous Airtel authentication handler."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._max_response_bytes = max_response_bytes
        self._cache = AirtelTokenCache()
        self._loop_locks: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, asyncio.Lock
        ] = weakref.WeakKeyDictionary()
        self._loop_locks_guard = threading.Lock()

    def __repr__(self) -> str:
        return (
            f"AsyncAirtelAuth(client_id={self._client_id!r}, "
            f"client_secret=<redacted>, base_url={self._base_url!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        with self._loop_locks_guard:
            lock = self._loop_locks.get(loop)
            if lock is None:
                lock = asyncio.Lock()
                self._loop_locks[loop] = lock
            return lock

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
            response = await client.send(req, stream=True, follow_redirects=False)
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
                async for chunk in response.aiter_bytes():
                    if len(buf) + len(chunk) > self._max_response_bytes:
                        raise PyMomoSDKError(
                            f"Response body exceeded maximum allowed size of {self._max_response_bytes} bytes"
                        )
                    buf.extend(chunk)
                response._content = bytes(buf)
            finally:
                await response.aclose()
        except httpx.TimeoutException:
            raise PyMomoSDKError("Airtel authentication request timed out") from None
        except httpx.RequestError:
            raise PyMomoSDKError(
                "Airtel authentication request connection error"
            ) from None

        token, expires_in_int = _parse_airtel_token_payload(response)
        self._cache.set(token, expires_in_int)
        return token

    def invalidate(self, *, expected_token: str | None = None) -> None:
        """Invalidate the cached token, forcing a refresh on next call."""
        self._cache.invalidate(expected_token=expected_token)
