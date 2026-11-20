from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from pymomo.airtel.auth import AirtelAuth
from pymomo.airtel.config import AirtelConfig
from pymomo.airtel.products.collection import Collection
from pymomo.airtel.products.disbursement import Disbursement
from pymomo.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    MomoServerError,
    PyMoMoError,
    ResourceNotFoundError,
)
from pymomo.utils import (
    validate_base_url,
    validate_header_value,
    validate_request_path,
)

if TYPE_CHECKING:
    from typing_extensions import Self

logger = logging.getLogger("pymomo.airtel.client")


class AirtelClient:
    """Synchronous Airtel Money API client.

    Instantiate with an AirtelConfig and access products via attributes.
    """

    def __init__(self, config: AirtelConfig) -> None:
        self._config = config

        base_url = validate_base_url(self._config.base_url or "")

        self._auth = AirtelAuth(
            client_id=config.client_id,
            client_secret=config.client_secret,
            base_url=base_url,
        )

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
            self._collection = Collection(client=self)
        return self._collection

    @property
    def disbursement(self) -> Disbursement:
        """Get Airtel Disbursement product client instance."""
        if self._disbursement is None:
            self._disbursement = Disbursement(client=self)
        return self._disbursement

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
            raise PyMoMoError("HTTP method must be a valid ASCII token")
        method = method.upper()
        validate_request_path(path)
        # 1. Build standard headers
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
                    raise PyMoMoError("HTTP header name is invalid")
                try:
                    validate_header_value(key, field_name="header name")
                    validate_header_value(value, field_name=key)
                except ValueError as exc:
                    raise PyMoMoError(str(exc)) from None
                if key.lower() == "authorization":
                    continue
                req_headers[key] = value

        # 2. Get and inject bearer token
        token = self._auth.get_token(self._http)
        req_headers["Authorization"] = f"Bearer {token}"

        # Debug level logging only for method and path
        logger.debug("%s %s", method, path)

        try:
            response = self._http.request(
                method,
                path,
                headers=req_headers,
                json=json,
            )
        except httpx.TimeoutException:
            raise PyMoMoError(f"Airtel request timed out: {method} {path}") from None
        except httpx.RequestError:
            raise PyMoMoError(f"Airtel connection error: {method} {path}") from None

        # 3. Handle 401 retry logic
        if response.status_code == 401:
            logger.debug("Airtel 401 detected, invalidating cache and retrying")
            self._auth.invalidate(expected_token=token)

            try:
                new_token = self._auth.get_token(self._http)
            except (PyMoMoError, ValueError):
                raise AuthenticationError(
                    "Airtel authentication failed during token refresh"
                ) from None

            retry_headers = req_headers.copy()
            retry_headers["Authorization"] = f"Bearer {new_token}"

            logger.debug("Retrying Airtel %s %s with new token", method, path)
            try:
                response = self._http.request(
                    method,
                    path,
                    headers=retry_headers,
                    json=json,
                )
            except httpx.TimeoutException:
                raise PyMoMoError(
                    f"Airtel request timed out on retry: {method} {path}"
                ) from None
            except httpx.RequestError:
                raise PyMoMoError(
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
            raise MomoServerError(f"Airtel server error: {response.status_code}")
        raise PyMoMoError(f"Unexpected Airtel HTTP status: {response.status_code}")

    def close(self) -> None:
        """Close the underlying HttpClient session."""
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
