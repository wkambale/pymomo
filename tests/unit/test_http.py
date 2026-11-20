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
    client = HttpClient("https://example.com", 30.0)
    assert client._client.follow_redirects is False


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://localhost:80@evil.example.com",
        "http://127.0.0.1:80@evil.example.com",
        "http://localhost@evil.example.com",
        " http://evil.example.com",
        "https://example.com ",
        "ftp://evil.example.com",
        "",
        "http://localhost\\@evil.example.com",
        "https://user:pass@example.com",
        "https://example.com?foo=bar",
        "https://example.com#frag",
        "https://example.com\r\nX-Injected: true",
    ],
)
def test_https_enforcement_rejects_url_parser_bypasses(bad_url: str) -> None:
    """Verify URL parser differentials and unsafe schemes are rejected."""
    with pytest.raises(PyMoMoError):
        HttpClient(bad_url, 30.0)
    with pytest.raises(PyMoMoError):
        AsyncHttpClient(bad_url, 30.0)


@pytest.mark.parametrize(
    "bad_path",
    [
        "http://evil.example.com/steal",
        "https://evil.example.com/steal",
        "//evil.example.com/steal",
        "relative/without/slash",
        "",
        "/path\\evil",
        "/path\r\nX-Injected: 1",
    ],
)
def test_request_rejects_non_relative_paths_sync(bad_path: str) -> None:
    """Verify HttpClient.request rejects absolute or protocol-relative paths."""
    client = HttpClient("https://example.com", 30.0)
    with pytest.raises(PyMoMoError):
        client.request("GET", bad_path, headers={})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_path",
    [
        "http://evil.example.com/steal",
        "https://evil.example.com/steal",
        "//evil.example.com/steal",
        "relative/without/slash",
    ],
)
async def test_request_rejects_non_relative_paths_async(bad_path: str) -> None:
    """Verify AsyncHttpClient.request rejects absolute or protocol-relative paths."""
    client = AsyncHttpClient("https://example.com", 30.0)
    with pytest.raises(PyMoMoError):
        await client.request("GET", bad_path, headers={})


def test_clients_reject_missing_base_url_without_assert() -> None:
    """Verify MomoClient and AsyncMomoClient reject empty base_url cleanly."""
    from pymomo import AsyncMomoClient, MomoClient
    from pymomo.config import MomoConfig

    config = MomoConfig()
    config.base_url = ""
    with pytest.raises(PyMoMoError, match="Base URL must use HTTPS"):
        MomoClient(config)
    with pytest.raises(PyMoMoError, match="Base URL must use HTTPS"):
        AsyncMomoClient(config)


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


def test_http_exceptions_do_not_chain_raw_httpx_request_headers() -> None:
    """Verify httpx exceptions are not chained via __cause__ onto PyMoMoError."""
    client = HttpClient("https://example.com", 30.0)
    req = httpx.Request(
        "GET",
        "https://example.com/secret",
        headers={
            "Authorization": "Bearer live-secret-token",
            "Ocp-Apim-Subscription-Key": "live-sub-key",
        },
    )
    with patch.object(
        client._client,
        "request",
        side_effect=httpx.ReadTimeout("timed out", request=req),
    ):
        with pytest.raises(PyMoMoError) as excinfo:
            client.request("GET", "/secret", headers=dict(req.headers))
        assert excinfo.value.__cause__ is None
        assert "live-secret-token" not in str(excinfo.value)
        assert "live-sub-key" not in str(excinfo.value)


def test_non_dict_json_error_body_and_parse_json_dict(httpx_mock: HTTPXMock) -> None:
    """Verify non-dict 400 JSON bodies and invalid 200 JSON bodies raise PyMoMoError."""
    from pymomo.http import parse_json_dict

    client = HttpClient("https://example.com", 30.0)
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/list-400",
        json=["not", "a", "dict"],
        status_code=400,
    )
    with pytest.raises(BadRequestError, match="Bad request") as excinfo:
        client.request("GET", "/list-400", headers={})
    assert excinfo.value.response_body == {}

    html_resp = httpx.Response(200, text="<html>error</html>")
    with pytest.raises(PyMoMoError, match="invalid JSON"):
        parse_json_dict(html_resp)

    list_resp = httpx.Response(200, json=[1, 2, 3])
    with pytest.raises(PyMoMoError, match="non-object JSON"):
        parse_json_dict(list_resp)
