from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.exceptions import (
    BadRequestError,
    ConflictError,
    PyMomoSDKError,
    PyMomoSDKServerError,
    ResourceNotFoundError,
)
from py_momo_sdk.http import HttpClient


def test_https_enforcement_sync() -> None:
    """Verify sync HttpClient constructor raises PyMomoSDKError on non-HTTPS schemes."""
    # Invalid HTTP
    with pytest.raises(PyMomoSDKError) as excinfo:
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
    with pytest.raises(PyMomoSDKError):
        HttpClient(bad_url, 30.0)
    with pytest.raises(PyMomoSDKError):
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
    with pytest.raises(PyMomoSDKError):
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
    with pytest.raises(PyMomoSDKError):
        await client.request("GET", bad_path, headers={})


def test_clients_reject_missing_base_url_without_assert() -> None:
    """Verify PyMomoSDK and AsyncPyMomoSDK reject empty base_url cleanly."""
    from py_momo_sdk import AsyncPyMomoSDK, PyMomoSDK
    from py_momo_sdk.config import PyMomoSDKConfig

    config = PyMomoSDKConfig()
    object.__setattr__(config, "base_url", "")
    with pytest.raises(PyMomoSDKError, match="Base URL must use HTTPS"):
        PyMomoSDK(config)
    with pytest.raises(PyMomoSDKError, match="Base URL must use HTTPS"):
        AsyncPyMomoSDK(config)


@pytest.mark.asyncio
async def test_https_enforcement_async() -> None:
    """Verify AsyncHttpClient constructor raises PyMomoSDKError on non-HTTPS schemes."""
    with pytest.raises(PyMomoSDKError) as excinfo:
        AsyncHttpClient("http://example.com", 30.0)
    assert "Base URL must use HTTPS" in str(excinfo.value)

    AsyncHttpClient("http://localhost", 30.0)
    AsyncHttpClient("https://example.com", 30.0)


def test_http_exceptions_handling_sync() -> None:
    """Verify connection errors and timeouts raise PyMomoSDKError in sync client."""
    client = HttpClient("https://example.com", 30.0)

    # Timeout
    with patch.object(
        client._client, "send", side_effect=httpx.TimeoutException("timeout")
    ):
        with pytest.raises(PyMomoSDKError) as excinfo:
            client.request("GET", "/test", headers={})
        assert "Request timed out" in str(excinfo.value)

    # Connection Error
    with patch.object(
        client._client, "send", side_effect=httpx.RequestError("connect")
    ):
        with pytest.raises(PyMomoSDKError) as excinfo:
            client.request("GET", "/test", headers={})
        assert "Connection error" in str(excinfo.value)


@pytest.mark.asyncio
async def test_http_exceptions_handling_async() -> None:
    """Verify connection errors and timeouts raise PyMomoSDKError in async client."""
    client = AsyncHttpClient("https://example.com", 30.0)

    # Timeout
    with patch.object(
        client._client, "send", side_effect=httpx.TimeoutException("timeout")
    ):
        with pytest.raises(PyMomoSDKError) as excinfo:
            await client.request("GET", "/test", headers={})
        assert "Request timed out" in str(excinfo.value)

    # Connection Error
    with patch.object(
        client._client, "send", side_effect=httpx.RequestError("connect")
    ):
        with pytest.raises(PyMomoSDKError) as excinfo:
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
    with pytest.raises(PyMomoSDKServerError):
        client.request("GET", "/test-500", headers={})

    # 418 Unexpected status
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/test-418",
        status_code=418,
    )
    with pytest.raises(PyMomoSDKError) as exc418:
        client.request("GET", "/test-418", headers={})
    assert "Unexpected HTTP status: 418" in str(exc418.value)


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
    with pytest.raises(PyMomoSDKServerError):
        await client.request("GET", "/test-500", headers={})


def test_http_exceptions_do_not_chain_raw_httpx_request_headers() -> None:
    """Verify httpx exceptions are not chained via __cause__ onto PyMomoSDKError."""
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
        "send",
        side_effect=httpx.ReadTimeout("timed out", request=req),
    ):
        with pytest.raises(PyMomoSDKError) as excinfo:
            client.request("GET", "/secret", headers=dict(req.headers))
        assert excinfo.value.__cause__ is None
        assert "live-secret-token" not in str(excinfo.value)
        assert "live-sub-key" not in str(excinfo.value)


def test_non_dict_json_error_body_and_parse_json_dict(httpx_mock: HTTPXMock) -> None:
    """Verify non-dict 400 JSON bodies and invalid 200 JSON bodies raise PyMomoSDKError."""
    from py_momo_sdk.http import parse_json_dict

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
    with pytest.raises(PyMomoSDKError, match="invalid JSON"):
        parse_json_dict(html_resp)

    list_resp = httpx.Response(200, json=[1, 2, 3])
    with pytest.raises(PyMomoSDKError, match="non-object JSON"):
        parse_json_dict(list_resp)

    from py_momo_sdk.http import parse_model
    from py_momo_sdk.models import Balance

    bad_schema_resp = httpx.Response(200, json={"unexpected": "value"})
    with pytest.raises(PyMomoSDKError, match="did not match expected Balance schema"):
        parse_model(bad_schema_resp, Balance)


def test_redirects_injected_client_ownership_and_max_response_bytes_sync(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify 3xx rejection, injected client safety/ownership, and response byte bounds."""
    # 1. 302 redirect rejected rather than silently treated as success
    httpx_mock.add_response(
        method="POST",
        url="https://example.com/collection/v1_0/requesttopay",
        status_code=302,
        headers={"Location": "https://evil.example.com/collect"},
    )
    with (
        HttpClient("https://example.com", 10.0) as owned_client,
        pytest.raises(PyMomoSDKError, match="redirect HTTP status: 302"),
    ):
        owned_client.request("POST", "/collection/v1_0/requesttopay", headers={})

    # 2. Injected client with http:// base_url rejected
    insecure = httpx.Client(base_url="http://insecure.example.com")
    try:
        with pytest.raises(PyMomoSDKError, match="HTTPS"):
            HttpClient("https://example.com", 10.0, client=insecure)
    finally:
        insecure.close()

    # 3. Injected client (even with follow_redirects=True and empty base_url) is not closed
    #    and does NOT follow redirects
    shared = httpx.Client(follow_redirects=True)
    try:
        httpx_mock.add_response(
            method="GET",
            url="https://example.com/redir",
            status_code=307,
            headers={"Location": "https://evil.example.com/leak"},
        )
        with (
            HttpClient("https://example.com", 10.0, client=shared) as wrapped,
            pytest.raises(PyMomoSDKError, match="redirect HTTP status: 307"),
        ):
            wrapped.request(
                "GET",
                "/redir",
                headers={"Ocp-Apim-Subscription-Key": "secret-sub"},
            )
        assert shared.is_closed is False
        assert (
            len(httpx_mock.get_requests()) == 2
        )  # No request sent to evil.example.com
    finally:
        shared.close()

    # 4. Oversized response body rejected
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/huge",
        content=b"x" * 256,
        status_code=200,
    )
    with (
        HttpClient("https://example.com", 10.0, max_response_bytes=64) as small_cap,
        pytest.raises(PyMomoSDKError, match="maximum allowed size"),
    ):
        small_cap.request("GET", "/huge", headers={})


@pytest.mark.asyncio
async def test_redirects_injected_client_and_max_response_bytes_async(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify async 3xx rejection, injected AsyncClient ownership, and response bounds."""
    insecure = httpx.AsyncClient(base_url="http://insecure.example.com")
    try:
        with pytest.raises(PyMomoSDKError, match="HTTPS"):
            AsyncHttpClient("https://example.com", 10.0, client=insecure)
    finally:
        await insecure.aclose()

    shared = httpx.AsyncClient(follow_redirects=True)
    try:
        httpx_mock.add_response(
            method="POST",
            url="https://example.com/redir",
            status_code=302,
            headers={"Location": "https://evil.example.com/leak"},
        )
        async with AsyncHttpClient(
            "https://example.com", 10.0, client=shared
        ) as wrapped:
            with pytest.raises(PyMomoSDKError, match="redirect HTTP status: 302"):
                await wrapped.request("POST", "/redir", headers={})
        assert shared.is_closed is False

        httpx_mock.add_response(
            method="GET",
            url="https://example.com/huge",
            content=b"y" * 256,
            status_code=200,
        )
        async with AsyncHttpClient(
            "https://example.com", 10.0, max_response_bytes=64
        ) as small_cap:
            with pytest.raises(PyMomoSDKError, match="maximum allowed size"):
                await small_cap.request("GET", "/huge", headers={})
    finally:
        await shared.aclose()


@pytest.mark.asyncio
async def test_async_http_no_cause_chain_and_non_idempotent_post_no_retry(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify AsyncHttpClient strips __cause__ and never retries POST without X-Reference-Id (#65)."""
    async with AsyncHttpClient(
        "https://example.com", 10.0, max_retries=2, retry_backoff=0.01
    ) as client:
        req = httpx.Request(
            "GET",
            "https://example.com/secret",
            headers={
                "Authorization": "Bearer async-live-secret",
                "Ocp-Apim-Subscription-Key": "async-sub-secret",
            },
        )
        with patch.object(
            client._client,
            "send",
            side_effect=httpx.ReadTimeout("timed out", request=req),
        ):
            with pytest.raises(PyMomoSDKError) as excinfo:
                await client.request("GET", "/secret", headers=dict(req.headers))
            assert excinfo.value.__cause__ is None
            assert "async-live-secret" not in str(excinfo.value)
            assert "async-sub-secret" not in str(excinfo.value)

        # POST without X-Reference-Id (or blank X-Reference-Id) must NOT retry on 503
        httpx_mock.add_response(
            method="POST", url="https://example.com/write", status_code=503
        )
        with pytest.raises(PyMomoSDKServerError):
            await client.request("POST", "/write", headers={"X-Reference-Id": "   "})
        assert len(httpx_mock.get_requests()) == 1


def test_http_retry_safety_401_retry_after_and_attribution_issue_82() -> None:
    """Verify Retry-After clamping/HTTP-date, 401 error preservation, budget cap, lowercase bearer, telemetry, and MTN write safety (#82)."""
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    from py_momo_sdk import PyMomoSDK
    from py_momo_sdk.auth import TokenCache
    from py_momo_sdk.config import SANDBOX, ProductConfig, PyMomoSDKConfig
    from py_momo_sdk.exceptions import AuthenticationError
    from py_momo_sdk.http import _compute_retry_delay, _raise_for_status
    from py_momo_sdk.telemetry import RequestTelemetryEvent, TelemetryHook

    # 1. Retry-After > 30s clamped to 30.0 (not discarded), 0 -> 0.0, HTTP-date parsed
    assert _compute_retry_delay(
        0, 0.5, httpx.Response(429, headers={"Retry-After": "60"})
    ) == pytest.approx(30.0)
    assert (
        _compute_retry_delay(0, 0.5, httpx.Response(429, headers={"Retry-After": "0"}))
        == 0.0
    )
    future_http_date = format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=10), usegmt=True
    )
    date_delay = _compute_retry_delay(
        0, 0.5, httpx.Response(429, headers={"Retry-After": future_http_date})
    )
    assert 5.0 <= date_delay <= 12.0

    # 2. Provider-neutral error attribution & Daraja errorMessage / ConflictError.reference_id
    with pytest.raises(PyMomoSDKServerError, match="Wave server error: 502"):
        _raise_for_status(httpx.Response(502), provider_name="Wave")
    with pytest.raises(BadRequestError, match="Invalid Amount"):
        _raise_for_status(
            httpx.Response(
                400, json={"errorCode": "400.002", "errorMessage": "Invalid Amount"}
            )
        )
    with pytest.raises(ConflictError) as exc_409:
        _raise_for_status(httpx.Response(409), reference_id="ref-dup-1")
    assert exc_409.value.reference_id == "ref-dup-1"

    # 3. Lowercase 'bearer ' scheme preserves fresh token during 401 CAS invalidation
    tc = TokenCache()
    tc.set("collection", "fresh_T2", 3600)
    seen_cached: list[str | None] = []
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(401)),
            base_url="https://sandbox.momodeveloper.mtn.com",
        ) as raw_c,
        HttpClient("https://sandbox.momodeveloper.mtn.com", 10.0, client=raw_c) as hc,
        pytest.raises(AuthenticationError),
    ):
        hc.request(
            "GET",
            "/collection/v1_0/account/balance",
            headers={"Authorization": "bearer stale_T1"},
            product_name="collection",
            token_cache=tc,
            token_refresher=lambda: seen_cached.append(tc.get("collection")) or "T3",  # type: ignore[func-returns-value]
        )
    assert seen_cached == ["fresh_T2"]

    # 4. 401 refresh preserves upstream 503 PyMomoSDKServerError (does not mask as AuthenticationError)
    def refresh_503_handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/collection/token/":
            return httpx.Response(503)
        return httpx.Response(401)

    with (
        httpx.Client(
            transport=httpx.MockTransport(refresh_503_handler),
            base_url="https://sandbox.momodeveloper.mtn.com",
        ) as raw_c,
        HttpClient("https://sandbox.momodeveloper.mtn.com", 10.0, client=raw_c) as hc,
        pytest.raises(PyMomoSDKServerError, match="503"),
    ):
        hc.request(
            "GET",
            "/collection/v1_0/account/balance",
            headers={"Authorization": "Bearer old"},
            product_name="collection",
            token_cache=TokenCache(),
            token_refresher=lambda: (
                hc.request("POST", "/collection/token/", headers={}),
                "never",
            )[1],
        )

    # 5. 401 retry does not double transient retry budget
    call_count = 0

    def budget_handler(req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return httpx.Response(503)
        if call_count == 3:
            return httpx.Response(401)
        return httpx.Response(503)

    with (
        httpx.Client(
            transport=httpx.MockTransport(budget_handler),
            base_url="https://sandbox.momodeveloper.mtn.com",
        ) as raw_c,
        HttpClient(
            "https://sandbox.momodeveloper.mtn.com",
            10.0,
            max_retries=2,
            retry_backoff=0.001,
            client=raw_c,
        ) as hc,
        pytest.raises(PyMomoSDKServerError),
    ):
        hc.request(
            "GET",
            "/collection/v1_0/account/balance",
            headers={"Authorization": "Bearer old"},
            product_name="collection",
            token_cache=TokenCache(),
            token_refresher=lambda: "new_tok",
        )
    assert call_count == 4

    # 6. Auto-generated MTN write does NOT silently retry on timeout; /token/ DOES retry on 503
    token_calls = 0
    write_calls = 0

    def mtn_handler(req: httpx.Request) -> httpx.Response:
        nonlocal token_calls, write_calls
        if req.url.path == "/collection/token/":
            token_calls += 1
            if token_calls == 1:
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={
                    "access_token": "tok",
                    "token_type": "access_token",
                    "expires_in": 3600,
                },
            )
        write_calls += 1
        raise httpx.ReadTimeout("timeout after MTN accepted")

    cfg = PyMomoSDKConfig(
        environment=SANDBOX,
        max_retries=2,
        retry_backoff=0.001,
        collection=ProductConfig("sub", "user", "key"),
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(mtn_handler),
            base_url="https://sandbox.momodeveloper.mtn.com",
        ) as injected,
        PyMomoSDK(cfg, client=injected, max_response_bytes=4096) as sdk,
        pytest.raises(PyMomoSDKError, match="timed out"),
    ):
        sdk.collection.request_to_pay("100", "EUR", "256771234567", "ord-1")
    assert token_calls == 2
    assert write_calls == 1

    # 7. Telemetry emitted on oversized-response rejection
    events: list[RequestTelemetryEvent] = []

    class _Hook(TelemetryHook):
        def on_request(self, event: RequestTelemetryEvent) -> None:
            events.append(event)

        def on_webhook(self, event: object) -> None:
            return None

    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=b"x" * 200)
            ),
            base_url="https://example.com",
        ) as raw_c,
        HttpClient(
            "https://example.com",
            10.0,
            max_response_bytes=64,
            client=raw_c,
            telemetry=_Hook(),
        ) as hc,
        pytest.raises(PyMomoSDKError, match="maximum allowed size"),
    ):
        hc.request("GET", "/big", headers={})
    assert len(events) == 1
    assert events[0].error_type == "ResponseTooLargeError"
