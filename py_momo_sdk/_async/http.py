from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import httpx

from py_momo_sdk.auth import TokenCache
from py_momo_sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    PyMomoSDKError,
    PyMomoSDKServerError,
    ResourceNotFoundError,
)
from py_momo_sdk.utils import validate_base_url, validate_request_path

if TYPE_CHECKING:
    from typing_extensions import Self

logger = logging.getLogger("py_momo_sdk.http")


class AsyncHttpClient:
    """Thin wrapper around httpx.AsyncClient with retry logic and error mappings."""

    def __init__(self, base_url: str, timeout: float) -> None:
        validated_url = validate_base_url(base_url)
        self._client = httpx.AsyncClient(
            base_url=validated_url,
            timeout=timeout,
            follow_redirects=False,
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
        validate_request_path(path)
        logger.debug("%s %s", method, path)
        try:
            response = await self._client.request(
                method, path, headers=headers, json=json, data=data
            )
        except httpx.TimeoutException:
            raise PyMomoSDKError(f"Request timed out: {method} {path}") from None
        except httpx.RequestError:
            raise PyMomoSDKError(f"Connection error: {method} {path}") from None

        if (
            response.status_code == 401
            and token_refresher
            and token_cache
            and product_name
        ):
            # Only invalidate if cache still holds the token that just failed
            auth_val = headers.get("Authorization", "")
            failed_token = auth_val[7:] if auth_val.startswith("Bearer ") else None
            token_cache.invalidate(product_name, expected_token=failed_token)

            # Re-fetch a token asynchronously
            try:
                new_token = await token_refresher()
            except (PyMomoSDKError, ValueError):
                raise AuthenticationError(
                    "Authentication failed during token refresh"
                ) from None

            # Retry original request exactly once
            retry_headers = headers.copy()
            retry_headers["Authorization"] = f"Bearer {new_token}"

            logger.debug("Retrying %s %s with new token", method, path)
            try:
                response = await self._client.request(
                    method, path, headers=retry_headers, json=json, data=data
                )
            except httpx.TimeoutException:
                raise PyMomoSDKError(
                    f"Request timed out on retry: {method} {path}"
                ) from None
            except httpx.RequestError:
                raise PyMomoSDKError(
                    f"Connection error on retry: {method} {path}"
                ) from None

        _raise_for_status(response)
        return response

    async def close(self) -> None:
        """Close the underlying client session."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


def _raise_for_status(response: httpx.Response) -> None:
    """Map HTTP status codes to custom exception classes."""
    if response.status_code < 400:
        return
    body: dict[str, Any] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
    except ValueError:
        body = {}

    if response.status_code == 400:
        raise BadRequestError(body.get("message", "Bad request"), response_body=body)
    if response.status_code == 401:
        raise AuthenticationError("Invalid or expired credentials")
    if response.status_code == 404:
        raise ResourceNotFoundError("Resource not found")
    if response.status_code == 409:
        raise ConflictError("Duplicate X-Reference-Id")
    if response.status_code >= 500:
        raise PyMomoSDKServerError(f"MTN server error: {response.status_code}")
    raise PyMomoSDKError(f"Unexpected HTTP status: {response.status_code}")
