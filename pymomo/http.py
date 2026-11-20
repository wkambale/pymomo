from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from pymomo.auth import TokenCache
from pymomo.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    MomoServerError,
    PyMoMoError,
    ResourceNotFoundError,
)
from pymomo.utils import validate_base_url, validate_request_path

if TYPE_CHECKING:
    from typing_extensions import Self

logger = logging.getLogger("pymomo.http")


class HttpClient:
    """Thin wrapper around httpx.Client with retry logic and error mappings."""

    def __init__(self, base_url: str, timeout: float) -> None:
        validated_url = validate_base_url(base_url)
        self._client = httpx.Client(
            base_url=validated_url,
            timeout=timeout,
            follow_redirects=False,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json: Any = None,
        data: Any = None,
        product_name: str | None = None,
        token_cache: TokenCache | None = None,
        token_refresher: Callable[[], str] | None = None,
    ) -> httpx.Response:
        """Execute HTTP request with 401 retry mapping."""
        validate_request_path(path)
        logger.debug("%s %s", method, path)
        try:
            response = self._client.request(
                method, path, headers=headers, json=json, data=data
            )
        except httpx.TimeoutException:
            raise PyMoMoError(f"Request timed out: {method} {path}") from None
        except httpx.RequestError:
            raise PyMoMoError(f"Connection error: {method} {path}") from None

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

            # Re-fetch a token
            try:
                new_token = token_refresher()
            except (PyMoMoError, ValueError):
                raise AuthenticationError(
                    "Authentication failed during token refresh"
                ) from None

            # Retry original request exactly once
            retry_headers = headers.copy()
            retry_headers["Authorization"] = f"Bearer {new_token}"

            logger.debug("Retrying %s %s with new token", method, path)
            try:
                response = self._client.request(
                    method, path, headers=retry_headers, json=json, data=data
                )
            except httpx.TimeoutException:
                raise PyMoMoError(
                    f"Request timed out on retry: {method} {path}"
                ) from None
            except httpx.RequestError:
                raise PyMoMoError(
                    f"Connection error on retry: {method} {path}"
                ) from None

        _raise_for_status(response)
        return response

    def close(self) -> None:
        """Close the underlying client session."""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


ModelT = TypeVar("ModelT", bound=BaseModel)


def parse_json_dict(response: httpx.Response) -> dict[str, Any]:
    """Decode an HTTP response body as a JSON object.

    Raises:
        PyMoMoError: If the response body is not valid JSON or not a JSON object.
    """
    try:
        parsed = response.json()
    except ValueError:
        raise PyMoMoError("API returned invalid JSON response") from None
    if not isinstance(parsed, dict):
        raise PyMoMoError("API returned unexpected non-object JSON response")
    return parsed


def parse_model(response: httpx.Response, model_cls: type[ModelT]) -> ModelT:
    """Decode a JSON object response and validate it against a Pydantic model.

    Raises:
        PyMoMoError: If the response body is not valid JSON or does not match
            the expected model schema.
    """
    data = parse_json_dict(response)
    try:
        return model_cls.model_validate(data)
    except ValidationError:
        raise PyMoMoError(
            f"API response did not match expected {model_cls.__name__} schema"
        ) from None


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
        raise MomoServerError(f"MTN server error: {response.status_code}")
    raise PyMoMoError(f"Unexpected HTTP status: {response.status_code}")
