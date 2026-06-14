from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from pymomo._async.http import AsyncHttpClient
from pymomo.exceptions import (
    BadRequestError,
    ConflictError,
    MomoServerError,
    PyMoMoError,
    ResourceNotFoundError,
)
from pymomo.http import HttpClient


def test_https_enforcement_sync() -> None:
    """Verify sync HttpClient constructor raises PyMoMoError on non-HTTPS schemes."""
    # Invalid HTTP
    with pytest.raises(PyMoMoError) as excinfo:
        HttpClient("http://example.com", 30.0)
    assert "Base URL must use HTTPS" in str(excinfo.value)

    # Valid localhosts/127.0.0.1 HTTP
    HttpClient("http://localhost", 30.0)
    HttpClient("http://localhost:8000", 30.0)
    HttpClient("http://127.0.0.1", 30.0)
    HttpClient("http://127.0.0.1:8080", 30.0)

    # Valid HTTPS
    HttpClient("https://example.com", 30.0)


@pytest.mark.asyncio
async def test_https_enforcement_async() -> None:
    """Verify AsyncHttpClient constructor raises PyMoMoError on non-HTTPS schemes."""
    with pytest.raises(PyMoMoError) as excinfo:
        AsyncHttpClient("http://example.com", 30.0)
    assert "Base URL must use HTTPS" in str(excinfo.value)

    AsyncHttpClient("http://localhost", 30.0)
    AsyncHttpClient("https://example.com", 30.0)


def test_http_exceptions_handling_sync() -> None:
    """Verify connection errors and timeouts raise PyMoMoError in sync client."""
    client = HttpClient("https://example.com", 30.0)

    # Timeout
    with patch.object(
        client._client, "request", side_effect=httpx.TimeoutException("timeout")
    ):
        with pytest.raises(PyMoMoError) as excinfo:
            client.request("GET", "/test", headers={})
        assert "Request timed out" in str(excinfo.value)

    # Connection Error
    with patch.object(
        client._client, "request", side_effect=httpx.RequestError("connect")
    ):
        with pytest.raises(PyMoMoError) as excinfo:
            client.request("GET", "/test", headers={})
        assert "Connection error" in str(excinfo.value)


@pytest.mark.asyncio
async def test_http_exceptions_handling_async() -> None:
    """Verify connection errors and timeouts raise PyMoMoError in async client."""
    client = AsyncHttpClient("https://example.com", 30.0)

    # Timeout
    with patch.object(
        client._client, "request", side_effect=httpx.TimeoutException("timeout")
    ):
        with pytest.raises(PyMoMoError) as excinfo:
            await client.request("GET", "/test", headers={})
        assert "Request timed out" in str(excinfo.value)

    # Connection Error
    with patch.object(
        client._client, "request", side_effect=httpx.RequestError("connect")
    ):
        with pytest.raises(PyMoMoError) as excinfo:
            await client.request("GET", "/test", headers={})
        assert "Connection error" in str(excinfo.value)


def test_status_code_mappings_sync(httpx_mock: HTTPXMock) -> None:
    """Verify standard status code mapping exceptions in sync HttpClient."""
    client = HttpClient("https://example.com", 30.0)

    # 400 Bad Request
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/test-400",
        json={"message": "invalid params"},
        status_code=400,
    )
    with pytest.raises(BadRequestError) as excinfo:
        client.request("GET", "/test-400", headers={})
    assert "invalid params" in str(excinfo.value)

    # 404 Not Found
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/test-404",
        status_code=404,
    )
    with pytest.raises(ResourceNotFoundError):
        client.request("GET", "/test-404", headers={})

    # 409 Conflict
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/test-409",
        status_code=409,
    )
    with pytest.raises(ConflictError):
        client.request("GET", "/test-409", headers={})

    # 500 Server Error
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/test-500",
        status_code=500,
    )
    with pytest.raises(MomoServerError):
        client.request("GET", "/test-500", headers={})

    # 418 Unexpected status
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/test-418",
        status_code=418,
    )
    with pytest.raises(PyMoMoError) as excinfo:
        client.request("GET", "/test-418", headers={})
    assert "Unexpected HTTP status: 418" in str(excinfo.value)


@pytest.mark.asyncio
async def test_status_code_mappings_async(httpx_mock: HTTPXMock) -> None:
    """Verify standard status code mapping exceptions in AsyncHttpClient."""
    client = AsyncHttpClient("https://example.com", 30.0)

    # 400 Bad Request
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/test-400",
        json={"message": "invalid params"},
        status_code=400,
    )
    with pytest.raises(BadRequestError) as excinfo:
        await client.request("GET", "/test-400", headers={})
    assert "invalid params" in str(excinfo.value)

    # 404 Not Found
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/test-404",
        status_code=404,
    )
    with pytest.raises(ResourceNotFoundError):
        await client.request("GET", "/test-404", headers={})

    # 409 Conflict
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/test-409",
        status_code=409,
    )
    with pytest.raises(ConflictError):
        await client.request("GET", "/test-409", headers={})

    # 500 Server Error
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/test-500",
        status_code=500,
    )
    with pytest.raises(MomoServerError):
        await client.request("GET", "/test-500", headers={})
