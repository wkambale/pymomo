from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

import httpx

from pymomo.auth import TokenCache
from pymomo.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    MomoServerError,
    PyMoMoError,
    ResourceNotFoundError,
)

logger = logging.getLogger("pymomo.http")


class AsyncHttpClient:
    """Thin wrapper around httpx.AsyncClient with retry logic and error mappings."""

    def __init__(self, base_url: str, timeout: float) -> None:
        # Check HTTPS requirement (except for localhost/127.0.0.1)
        parsed_url = base_url.lower()
        if parsed_url.startswith("http://"):
            host = parsed_url[7:].split("/")[0].split(":")[0]
            if host not in ("localhost", "127.0.0.1"):
                raise PyMoMoError("Base URL must use HTTPS")

        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
        )

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
    ) -> httpx.Response:
        """Execute async HTTP request with 401 retry mapping."""
        logger.debug("%s %s", method, path)
        try:
            response = await self._client.request(
                method, path, headers=headers, json=json, data=data
            )
        except httpx.TimeoutException as exc:
            raise PyMoMoError(f"Request timed out: {method} {path}") from exc
        except httpx.RequestError as exc:
            raise PyMoMoError(f"Connection error: {method} {path}") from exc

        if (
            response.status_code == 401
            and token_refresher
            and token_cache
            and product_name
        ):
            # Invalidate cache entry
            token_cache.invalidate(product_name)

            # Re-fetch a token asynchronously
            try:
                new_token = await token_refresher()
            except Exception as exc:
                raise AuthenticationError(
                    "Authentication failed during token refresh"
                ) from exc

            # Retry original request exactly once
            retry_headers = headers.copy()
            retry_headers["Authorization"] = f"Bearer {new_token}"

            logger.debug("Retrying %s %s with new token", method, path)
            try:
                response = await self._client.request(
                    method, path, headers=retry_headers, json=json, data=data
                )
            except httpx.TimeoutException as exc:
                raise PyMoMoError(
                    f"Request timed out on retry: {method} {path}"
                ) from exc
            except httpx.RequestError as exc:
                raise PyMoMoError(
                    f"Connection error on retry: {method} {path}"
                ) from exc

        _raise_for_status(response)
        return response

    async def close(self) -> None:
        """Close the underlying client session."""
        await self._client.aclose()

    async def __aenter__(self) -> AsyncHttpClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


def _raise_for_status(response: httpx.Response) -> None:
    """Map HTTP status codes to custom exception classes."""
    if response.status_code < 400:
        return
    body: dict[str, Any] = {}
    try:
        body = response.json()
    except Exception:
        pass

    if response.status_code == 400:
        raise BadRequestError(body.get("message", "Bad request"), response_body=body)
    if response.status_code == 401:
        raise AuthenticationError("Invalid or expired credentials")
    if response.status_code == 404:
        raise ResourceNotFoundError("Resource not found")
    if response.status_code == 409:
        raise ConflictError("Duplicate X-Reference-Id")
    if response.status_code >= 500:
        raise MomoServerError(f"MTN server error: {response.status_code}")
    raise PyMoMoError(f"Unexpected HTTP status: {response.status_code}")
