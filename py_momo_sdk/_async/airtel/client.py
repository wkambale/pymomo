from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from py_momo_sdk._async.airtel.auth import AsyncAirtelAuth
from py_momo_sdk._async.airtel.products.collection import AsyncAirtelCollection
from py_momo_sdk._async.airtel.products.disbursement import AsyncAirtelDisbursement
from py_momo_sdk.airtel.config import AirtelConfig
from py_momo_sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    PyMomoSDKError,
    PyMomoSDKServerError,
    ResourceNotFoundError,
)
from py_momo_sdk.utils import (
    validate_base_url,
    validate_header_value,
    validate_request_path,
)

if TYPE_CHECKING:
    from typing_extensions import Self

logger = logging.getLogger("py_momo_sdk.airtel.client")


class AsyncAirtelClient:
    """Asynchronous Airtel Money API client.

    Instantiate with an AirtelConfig and access products via attributes.
    """

    def __init__(self, config: AirtelConfig) -> None:
        self._config = config
        base_url = validate_base_url(self._config.base_url or "")

        self._auth = AsyncAirtelAuth(
            client_id=config.client_id,
            client_secret=config.client_secret,
            base_url=base_url,
        )
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

        req_headers = {
            "X-Country": self._config.country,
            "X-Currency": self._config.currency,
            "Content-Type": "application/json",
        }
        if headers:
            for key, value in headers.items():
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
                if key.lower() == "authorization":
                    continue
                req_headers[key] = value

        token = await self._auth.get_token(self._http)
        req_headers["Authorization"] = f"Bearer {token}"

        logger.debug("%s %s", method, path)
        try:
            response = await self._http.request(
                method,
                path,
                headers=req_headers,
                json=json,
            )
        except httpx.TimeoutException:
            raise PyMomoSDKError(f"Airtel request timed out: {method} {path}") from None
        except httpx.RequestError:
            raise PyMomoSDKError(f"Airtel connection error: {method} {path}") from None

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
            logger.debug("Retrying Airtel %s %s with new token", method, path)
            try:
                response = await self._http.request(
                    method,
                    path,
                    headers=retry_headers,
                    json=json,
                )
            except httpx.TimeoutException:
                raise PyMomoSDKError(
                    f"Airtel request timed out on retry: {method} {path}"
                ) from None
            except httpx.RequestError:
                raise PyMomoSDKError(
                    f"Airtel connection error on retry: {method} {path}"
                ) from None

        self._raise_for_status(response)
        return response

    def _raise_for_status(self, response: httpx.Response) -> None:
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
            raise BadRequestError(
                body.get("message", "Bad request"), response_body=body
            )
        if response.status_code == 401:
            raise AuthenticationError("Invalid or expired Airtel credentials")
        if response.status_code == 404:
            raise ResourceNotFoundError("Resource not found")
        if response.status_code == 409:
            raise ConflictError("Duplicate X-Reference-Id")
        if response.status_code >= 500:
            raise PyMomoSDKServerError(f"Airtel server error: {response.status_code}")
        raise PyMomoSDKError(f"Unexpected Airtel HTTP status: {response.status_code}")

    async def close(self) -> None:
        """Close the underlying async HTTP session."""
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
