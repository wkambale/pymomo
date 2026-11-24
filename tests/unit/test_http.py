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


def test_structured_upstream_error_extraction_all_gateways_issue_116() -> None:
    """Verify _raise_for_status surfaces structured codes, reasons, and status details across all gateway schemas (#116)."""
    from py_momo_sdk.exceptions import AuthenticationError
    from py_momo_sdk.http import _raise_for_status

    # 1. MTN 400 with code + message
    with pytest.raises(BadRequestError) as exc_mtn_400:
        _raise_for_status(
            httpx.Response(
                400,
                json={
                    "code": "INVALID_CALLBACK_URL_HOST",
                    "message": "Callback URL host mismatch",
                },
            ),
            provider_name="MTN MoMo",
            reference_id="ref-mtn-1",
        )
    assert exc_mtn_400.value.status_code == 400
    assert exc_mtn_400.value.error_code == "INVALID_CALLBACK_URL_HOST"
    assert exc_mtn_400.value.reason == "Callback URL host mismatch"
    assert exc_mtn_400.value.provider == "MTN MoMo"
    assert exc_mtn_400.value.reference_id == "ref-mtn-1"
    assert "INVALID_CALLBACK_URL_HOST" in str(exc_mtn_400.value)
    assert "Callback URL host mismatch" in str(exc_mtn_400.value)

    # 2. MTN 400 with code only (no message field)
    with pytest.raises(BadRequestError) as exc_mtn_code_only:
        _raise_for_status(
            httpx.Response(400, json={"code": "PAYER_NOT_FOUND"}),
            provider_name="MTN MoMo",
        )
    assert exc_mtn_code_only.value.error_code == "PAYER_NOT_FOUND"
    assert "PAYER_NOT_FOUND" in str(exc_mtn_code_only.value)

    # 3. MTN 500 with structured error details
    with pytest.raises(PyMomoSDKServerError) as exc_mtn_500:
        _raise_for_status(
            httpx.Response(
                500,
                json={
                    "code": "INTERNAL_PROCESSING_ERROR",
                    "message": "Downstream ledger busy",
                },
            ),
            provider_name="MTN MoMo",
        )
    assert exc_mtn_500.value.status_code == 500
    assert exc_mtn_500.value.error_code == "INTERNAL_PROCESSING_ERROR"
    assert exc_mtn_500.value.reason == "Downstream ledger busy"
    assert "MTN MoMo server error: 500" in str(exc_mtn_500.value)
    assert "INTERNAL_PROCESSING_ERROR: Downstream ledger busy" in str(exc_mtn_500.value)

    # 4. M-Pesa 400 with errorCode + errorMessage
    with pytest.raises(BadRequestError) as exc_mpesa:
        _raise_for_status(
            httpx.Response(
                400,
                json={
                    "errorCode": "400.002.02",
                    "errorMessage": "Bad Request - Invalid Amount",
                },
            ),
            provider_name="M-Pesa",
        )
    assert exc_mpesa.value.error_code == "400.002.02"
    assert exc_mpesa.value.reason == "Bad Request - Invalid Amount"
    assert "400.002.02: Bad Request - Invalid Amount" in str(exc_mpesa.value)

    # 5. Wave 422 with code + message + validation details -> BadRequestError(status_code=422)
    with pytest.raises(BadRequestError) as exc_wave_422:
        _raise_for_status(
            httpx.Response(
                422,
                json={
                    "code": "validation-error",
                    "message": "Invalid checkout payload",
                    "details": [{"loc": ["amount"], "msg": "must be positive"}],
                },
            ),
            provider_name="Wave",
        )
    assert exc_wave_422.value.status_code == 422
    assert exc_wave_422.value.error_code == "validation-error"
    assert "amount: must be positive" in (exc_wave_422.value.reason or "")
    assert "validation-error" in str(exc_wave_422.value)

    # 6. Paystack / Flutterwave 400 with message + errors dict
    with pytest.raises(BadRequestError) as exc_paystack:
        _raise_for_status(
            httpx.Response(
                400,
                json={
                    "status": False,
                    "message": "Validation failed",
                    "errors": {"email": ["must be a valid email"]},
                },
            ),
            provider_name="Paystack",
        )
    assert "email: must be a valid email" in str(exc_paystack.value)

    # 7. Orange OAuth 401 with error + error_description
    with pytest.raises(AuthenticationError) as exc_orange_401:
        _raise_for_status(
            httpx.Response(
                401,
                json={
                    "error": "invalid_client",
                    "error_description": "Client secret expired",
                },
            ),
            provider_name="Orange Money",
        )
    assert exc_orange_401.value.status_code == 401
    assert exc_orange_401.value.error_code == "invalid_client"
    assert exc_orange_401.value.reason == "Client secret expired"
    assert (
        "Invalid or expired credentials: invalid_client: Client secret expired"
        in str(exc_orange_401.value)
    )

    # 8. HTTP 403, 404, 409, 429 preserve details and status_code
    with pytest.raises(PyMomoSDKError) as exc_403:
        _raise_for_status(
            httpx.Response(
                403,
                json={
                    "code": "FORBIDDEN_SCOPE",
                    "message": "Missing disbursement scope",
                },
            ),
            provider_name="MTN MoMo",
        )
    assert exc_403.value.status_code == 403
    assert exc_403.value.error_code == "FORBIDDEN_SCOPE"
    assert "MTN MoMo forbidden (HTTP 403)" in str(exc_403.value)
    assert "FORBIDDEN_SCOPE: Missing disbursement scope" in str(exc_403.value)

    with pytest.raises(ResourceNotFoundError) as exc_404:
        _raise_for_status(
            httpx.Response(
                404,
                json={"code": "RESOURCE_NOT_FOUND", "message": "Reference not found"},
            ),
            provider_name="MTN MoMo",
        )
    assert exc_404.value.status_code == 404
    assert exc_404.value.error_code == "RESOURCE_NOT_FOUND"
    assert "RESOURCE_NOT_FOUND: Reference not found" in str(exc_404.value)

    with pytest.raises(ConflictError) as exc_409:
        _raise_for_status(
            httpx.Response(
                409,
                json={
                    "code": "DUPLICATE_REFERENCE",
                    "message": "Reference already used",
                },
            ),
            provider_name="MTN MoMo",
            reference_id="dup-ref-409",
        )
    assert exc_409.value.status_code == 409
    assert exc_409.value.reference_id == "dup-ref-409"
    assert "DUPLICATE_REFERENCE: Reference already used" in str(exc_409.value)

    with pytest.raises(PyMomoSDKError) as exc_429:
        _raise_for_status(
            httpx.Response(
                429, json={"code": "RATE_LIMITED", "message": "Too many requests"}
            ),
            provider_name="Wave",
        )
    assert exc_429.value.status_code == 429
    assert exc_429.value.error_code == "RATE_LIMITED"
    assert "429" in str(exc_429.value)
    assert "RATE_LIMITED: Too many requests" in str(exc_429.value)

    # 9. Plain-text error body surfaced cleanly; HTML error page suppressed
    with pytest.raises(PyMomoSDKServerError) as exc_text:
        _raise_for_status(
            httpx.Response(503, text="Upstream maintenance window active"),
            provider_name="Wave",
        )
    assert "Upstream maintenance window active" in str(exc_text.value)
    assert exc_text.value.reason == "Upstream maintenance window active"

    with pytest.raises(PyMomoSDKServerError) as exc_html:
        _raise_for_status(
            httpx.Response(
                502,
                text="<!DOCTYPE html><html><body>502 Bad Gateway</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            provider_name="Wave",
        )
    assert exc_html.value.reason is None
    assert "<html" not in str(exc_html.value).lower()
    assert str(exc_html.value) == "Wave server error: 502"


@pytest.mark.asyncio
async def test_airtel_structured_errors_and_transport_subtypes_issue_116() -> None:
    """Verify Airtel HTTP errors, HTTP 200 status rejections, auth errors, and transport subtypes (#116)."""
    from py_momo_sdk._async.airtel.auth import AsyncAirtelAuth
    from py_momo_sdk.airtel.auth import AirtelAuth, _parse_airtel_token_payload
    from py_momo_sdk.airtel.client import _raise_for_airtel_status
    from py_momo_sdk.airtel.models import check_airtel_response_status
    from py_momo_sdk.exceptions import AuthenticationError, TransactionFailedError

    # 1. Airtel HTTP 400 / 422 / 500 with nested status & data.transaction.message
    with pytest.raises(BadRequestError) as exc_a400:
        _raise_for_airtel_status(
            httpx.Response(
                400,
                json={
                    "status": {
                        "result_code": "DP00800001006",
                        "message": "Invalid MSISDN format",
                    }
                },
            ),
            reference_id="airtel-ref-1",
        )
    assert exc_a400.value.status_code == 400
    assert exc_a400.value.error_code == "DP00800001006"
    assert exc_a400.value.provider == "Airtel Money"
    assert exc_a400.value.reference_id == "airtel-ref-1"
    assert "DP00800001006: Invalid MSISDN format" in str(exc_a400.value)

    with pytest.raises(BadRequestError) as exc_a422:
        _raise_for_airtel_status(
            httpx.Response(
                422,
                json={
                    "status": {"code": "422", "message": "Unprocessable transaction"}
                },
            )
        )
    assert exc_a422.value.status_code == 422
    assert exc_a422.value.provider == "Airtel Money"

    with pytest.raises(PyMomoSDKServerError) as exc_a500:
        _raise_for_airtel_status(
            httpx.Response(
                500,
                json={
                    "status": {
                        "result_code": "DP00800001099",
                        "message": "Switch offline",
                    }
                },
            )
        )
    assert exc_a500.value.status_code == 500
    assert exc_a500.value.error_code == "DP00800001099"
    assert "Airtel server error: 500" in str(exc_a500.value)
    assert "Switch offline" in str(exc_a500.value)

    # 2. Airtel HTTP 200 status.success=false with result_code -> structured fields
    with pytest.raises(TransactionFailedError) as exc_a200_fail:
        check_airtel_response_status(
            {
                "data": {
                    "transaction": {"status": "TF", "message": "Insufficient funds"}
                },
                "status": {
                    "success": False,
                    "result_code": "DP00800001001",
                    "message": "Transaction failed",
                },
            },
            reference_id="airtel-tx-1",
        )
    assert exc_a200_fail.value.reference_id == "airtel-tx-1"
    assert exc_a200_fail.value.status_code == 200
    assert exc_a200_fail.value.error_code == "DP00800001001"
    assert exc_a200_fail.value.provider == "Airtel Money"
    assert "DP00800001001: Insufficient funds" in str(exc_a200_fail.value)

    with pytest.raises(BadRequestError) as exc_a200_bad:
        check_airtel_response_status(
            {
                "status": {
                    "success": False,
                    "code": "400",
                    "result_code": "DP00800001006",
                    "message": "Invalid amount",
                }
            },
            reference_id="airtel-tx-2",
        )
    assert exc_a200_bad.value.reference_id == "airtel-tx-2"
    assert exc_a200_bad.value.status_code == 200
    assert exc_a200_bad.value.error_code == "DP00800001006"
    assert "DP00800001006: Invalid amount" in str(exc_a200_bad.value)

    with pytest.raises(PyMomoSDKError) as exc_a200_generic:
        check_airtel_response_status(
            {
                "status": {
                    "success": False,
                    "result_code": "DP00800001099",
                    "message": "Partner limit exceeded",
                }
            },
            reference_id="airtel-tx-3",
        )
    assert exc_a200_generic.value.reference_id == "airtel-tx-3"
    assert exc_a200_generic.value.status_code == 200
    assert exc_a200_generic.value.error_code == "DP00800001099"
    assert "DP00800001099: Partner limit exceeded" in str(exc_a200_generic.value)

    # 3. Airtel token endpoint 401 & 500 include gateway reason
    with pytest.raises(AuthenticationError) as exc_tok_401:
        _parse_airtel_token_payload(
            httpx.Response(
                401,
                json={"error": "invalid_client", "error_description": "Wrong secret"},
            )
        )
    assert exc_tok_401.value.status_code == 401
    assert exc_tok_401.value.error_code == "invalid_client"
    assert "Invalid or expired Airtel client credentials" in str(exc_tok_401.value)
    assert "Wrong secret" in str(exc_tok_401.value)

    with pytest.raises(AuthenticationError) as exc_tok_500:
        _parse_airtel_token_payload(
            httpx.Response(500, json={"message": "Auth gateway unavailable"})
        )
    assert exc_tok_500.value.status_code == 500
    assert "Airtel authentication failed: HTTP 500" in str(exc_tok_500.value)
    assert "Auth gateway unavailable" in str(exc_tok_500.value)

    # 4. Sync and async transport timeout/connection subtypes include safe class name without chaining __cause__
    with (
        HttpClient("https://example.com", 5.0, provider_name="Wave") as hc,
        patch.object(
            hc._client, "send", side_effect=httpx.ReadTimeout("secret-internal-detail")
        ),
        pytest.raises(PyMomoSDKError) as exc_sync_to,
    ):
        hc.request("GET", "/check", headers={})
    assert "(ReadTimeout)" in str(exc_sync_to.value)
    assert exc_sync_to.value.reason == "ReadTimeout"
    assert exc_sync_to.value.provider == "Wave"
    assert exc_sync_to.value.__cause__ is None
    assert "secret-internal-detail" not in str(exc_sync_to.value)

    async with AsyncHttpClient("https://example.com", 5.0, provider_name="Wave") as ahc:
        with (
            patch.object(
                ahc._client,
                "send",
                side_effect=httpx.ConnectError("internal-host-info"),
            ),
            pytest.raises(PyMomoSDKError) as exc_async_conn,
        ):
            await ahc.request("GET", "/check", headers={})
    assert "(ConnectError)" in str(exc_async_conn.value)
    assert exc_async_conn.value.reason == "ConnectError"
    assert exc_async_conn.value.provider == "Wave"
    assert exc_async_conn.value.__cause__ is None

    # 5. Airtel sync & async auth timeout includes subtype name without leaking secret
    auth_sync = AirtelAuth("cid", "csec", "https://openapiuat.airtel.africa")
    with (
        httpx.Client(base_url="https://openapiuat.airtel.africa") as raw_sync,
        patch.object(raw_sync, "send", side_effect=httpx.ConnectTimeout("boom")),
        pytest.raises(PyMomoSDKError) as exc_as,
    ):
        auth_sync.get_token(raw_sync)
    assert "(ConnectTimeout)" in str(exc_as.value)
    assert exc_as.value.provider == "Airtel Money"
    assert exc_as.value.__cause__ is None

    auth_async = AsyncAirtelAuth("cid", "csec", "https://openapiuat.airtel.africa")
    async with httpx.AsyncClient(
        base_url="https://openapiuat.airtel.africa"
    ) as raw_async:
        with (
            patch.object(raw_async, "send", side_effect=httpx.ReadTimeout("boom")),
            pytest.raises(PyMomoSDKError) as exc_aa,
        ):
            await auth_async.get_token(raw_async)
    assert "(ReadTimeout)" in str(exc_aa.value)
    assert exc_aa.value.provider == "Airtel Money"
    assert exc_aa.value.__cause__ is None


@pytest.mark.asyncio
async def test_reference_id_preserved_across_all_providers_sync_and_async_issue_115() -> (
    None
):
    """Verify exc.reference_id is preserved on failed writes across all 7 providers (sync & async) (#115)."""
    from py_momo_sdk import (
        AirtelClient,
        AirtelConfig,
        AsyncAirtelClient,
        AsyncPyMomoSDK,
        PyMomoSDK,
        PyMomoSDKConfig,
    )
    from py_momo_sdk.config import SANDBOX, ProductConfig
    from py_momo_sdk.exceptions import AuthenticationError
    from py_momo_sdk.providers import (
        AsyncFlutterwaveClient,
        AsyncMpesaClient,
        AsyncOrangeMoneyClient,
        AsyncPaystackClient,
        AsyncWaveClient,
        FlutterwaveClient,
        FlutterwaveConfig,
        MpesaClient,
        MpesaConfig,
        OrangeMoneyClient,
        OrangeMoneyConfig,
        PaystackClient,
        PaystackConfig,
        WaveClient,
        WaveConfig,
    )

    # 1. MTN MoMo (sync & async): auto-generated ref preserved on 500, timeout, AND token 401 failure
    seen_mtn_refs: list[str] = []

    def mtn_fail_500(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/collection/token/":
            return httpx.Response(
                200,
                json={
                    "access_token": "tok-mtn",
                    "token_type": "access_token",
                    "expires_in": 3600,
                },
            )
        seen_mtn_refs.append(req.headers["X-Reference-Id"])
        return httpx.Response(
            500, json={"code": "INTERNAL_ERROR", "message": "Ledger down"}
        )

    mtn_cfg = PyMomoSDKConfig(
        environment=SANDBOX,
        collection=ProductConfig("sub", "user", "key"),
        disbursement=ProductConfig("sub", "user", "key"),
        remittance=ProductConfig("sub", "user", "key"),
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(mtn_fail_500),
            base_url="https://sandbox.momodeveloper.mtn.com",
        ) as raw_mtn,
        PyMomoSDK(mtn_cfg, client=raw_mtn) as sdk,
        pytest.raises(PyMomoSDKServerError) as exc_mtn_sync,
    ):
        sdk.collection.request_to_pay("100", "EUR", "256771234567", "ord-1")
    assert exc_mtn_sync.value.reference_id == seen_mtn_refs[-1]
    assert exc_mtn_sync.value.status_code == 500
    assert "Ledger down" in str(exc_mtn_sync.value)

    # MTN pre-request token failure still preserves the generated/explicit reference_id
    explicit_mtn_ref = "11111111-2222-4333-8444-555555555555"
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(401, json={"message": "Bad API key"})
            ),
            base_url="https://sandbox.momodeveloper.mtn.com",
        ) as raw_mtn_401,
        PyMomoSDK(mtn_cfg, client=raw_mtn_401) as sdk,
        pytest.raises(AuthenticationError) as exc_mtn_tok,
    ):
        sdk.collection.request_to_pay(
            "100", "EUR", "256771234567", "ord-2", reference_id=explicit_mtn_ref
        )
    assert exc_mtn_tok.value.reference_id == explicit_mtn_ref

    # MTN async timeout preserves auto-generated ref
    def mtn_timeout_handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/disbursement/token/":
            return httpx.Response(
                200,
                json={
                    "access_token": "tok-d",
                    "token_type": "access_token",
                    "expires_in": 3600,
                },
            )
        seen_mtn_refs.append(req.headers["X-Reference-Id"])
        raise httpx.ReadTimeout("slow")

    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(mtn_timeout_handler),
            base_url="https://sandbox.momodeveloper.mtn.com",
        ) as raw_mtn_async,
        AsyncPyMomoSDK(mtn_cfg, client=raw_mtn_async) as asdk,
    ):
        with pytest.raises(PyMomoSDKError) as exc_mtn_async:
            await asdk.disbursement.transfer("50", "EUR", "256771234567", "ord-3")
    assert exc_mtn_async.value.reference_id == seen_mtn_refs[-1]
    assert "(ReadTimeout)" in str(exc_mtn_async.value)

    # 2. Airtel Money (sync & async): auto-generated ref preserved on HTTP 400 and timeout
    import json as _json

    seen_airtel_refs: list[str] = []

    def airtel_fail_400(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/auth/oauth2/token":
            return httpx.Response(
                200, json={"access_token": "air-tok", "expires_in": 3600}
            )
        body = _json.loads(req.content.decode())
        seen_airtel_refs.append(body["transaction"]["id"])
        return httpx.Response(
            400,
            json={
                "status": {"result_code": "DP00800001006", "message": "Invalid MSISDN"}
            },
        )

    air_cfg = AirtelConfig(
        client_id="cid",
        client_secret="csec",
        country="UG",
        currency="UGX",
        pin="enc-pin",
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(airtel_fail_400),
            base_url="https://openapiuat.airtel.africa",
        ) as raw_air,
        AirtelClient(air_cfg, client=raw_air) as air,
        pytest.raises(BadRequestError) as exc_air_sync,
    ):
        air.collection.request_to_pay("5000", "256752123456")
    assert exc_air_sync.value.reference_id == seen_airtel_refs[-1]
    assert exc_air_sync.value.error_code == "DP00800001006"

    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(airtel_fail_400),
            base_url="https://openapiuat.airtel.africa",
        ) as raw_air_async,
        AsyncAirtelClient(air_cfg, client=raw_air_async) as aair,
    ):
        with pytest.raises(BadRequestError) as exc_air_async:
            await aair.disbursement.transfer("5000", "256752123456")
    assert exc_air_async.value.reference_id == seen_airtel_refs[-1]

    # 3. Wave (sync & async): auto-generated client_reference preserved on 422
    seen_wave_refs: list[str] = []

    def wave_fail_422(req: httpx.Request) -> httpx.Response:
        body = _json.loads(req.content.decode())
        seen_wave_refs.append(body["client_reference"])
        return httpx.Response(
            422, json={"code": "invalid-amount", "message": "Amount too small"}
        )

    wave_cfg = WaveConfig(
        api_key="wave_sn_prod_123",
        success_url="https://merchant.example.com/ok",
        error_url="https://merchant.example.com/err",
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(wave_fail_422),
            base_url="https://api.wave.com",
        ) as raw_w,
        WaveClient(wave_cfg, client=raw_w) as wc,
        pytest.raises(BadRequestError) as exc_wave_sync,
    ):
        wc.create_checkout_session("100", "XOF")
    assert exc_wave_sync.value.reference_id == seen_wave_refs[-1]
    assert exc_wave_sync.value.status_code == 422

    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(wave_fail_422),
            base_url="https://api.wave.com",
        ) as raw_wa,
        AsyncWaveClient(wave_cfg, client=raw_wa) as awc,
    ):
        with pytest.raises(BadRequestError) as exc_wave_async:
            await awc.create_payout("100", "XOF", "221771234567")
    assert exc_wave_async.value.reference_id == seen_wave_refs[-1]

    # 4. M-Pesa (sync & async): AccountReference & OriginatorConversationID preserved on 500 & token 401
    seen_mpesa_refs: list[str] = []

    def mpesa_fail_500(req: httpx.Request) -> httpx.Response:
        if "/oauth/v1/generate" in str(req.url):
            return httpx.Response(
                200, json={"access_token": "mp-tok", "expires_in": "3599"}
            )
        body = _json.loads(req.content.decode())
        seen_mpesa_refs.append(
            body.get("OriginatorConversationID") or body.get("AccountReference")
        )
        return httpx.Response(
            500, json={"errorCode": "500.001.1001", "errorMessage": "Daraja busy"}
        )

    mpesa_cfg = MpesaConfig(
        consumer_key="ck",
        consumer_secret="cs",
        short_code="174379",
        passkey="pk",
        callback_url="https://merchant.example.com/cb",
        initiator_name="init",
        security_credential="sec-cred",
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(mpesa_fail_500),
            base_url="https://sandbox.safaricom.co.ke",
        ) as raw_mp,
        MpesaClient(mpesa_cfg, client=raw_mp) as mc,
        pytest.raises(PyMomoSDKServerError) as exc_mp_sync,
    ):
        mc.b2c_transfer("100", "254712345678")
    assert exc_mp_sync.value.reference_id == seen_mpesa_refs[-1]
    assert exc_mp_sync.value.error_code == "500.001.1001"

    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(mpesa_fail_500),
            base_url="https://sandbox.safaricom.co.ke",
        ) as raw_mpa,
        AsyncMpesaClient(mpesa_cfg, client=raw_mpa) as amc,
    ):
        with pytest.raises(PyMomoSDKServerError) as exc_mp_async:
            await amc.stk_push("100", "254712345678", account_reference="INV-42")
    assert exc_mp_async.value.reference_id == "INV-42"

    # 5. Paystack (sync & async): auto-generated ref preserved on 400 and invalid JSON
    seen_ps_refs: list[str] = []

    def paystack_fail_400(req: httpx.Request) -> httpx.Response:
        body = _json.loads(req.content.decode())
        seen_ps_refs.append(body["reference"])
        return httpx.Response(400, json={"status": False, "message": "Duplicate ref"})

    ps_cfg = PaystackConfig(secret_key="sk_test_123")
    with (
        httpx.Client(
            transport=httpx.MockTransport(paystack_fail_400),
            base_url="https://api.paystack.co",
        ) as raw_ps,
        PaystackClient(ps_cfg, client=raw_ps) as psc,
        pytest.raises(BadRequestError) as exc_ps_sync,
    ):
        psc.initialize_transaction("a@example.com", "100", "NGN")
    assert exc_ps_sync.value.reference_id == seen_ps_refs[-1]

    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(paystack_fail_400),
            base_url="https://api.paystack.co",
        ) as raw_psa,
        AsyncPaystackClient(ps_cfg, client=raw_psa) as apsc,
    ):
        with pytest.raises(BadRequestError) as exc_ps_async:
            await apsc.initiate_transfer("100", "NGN", "RCP_12345")
    assert exc_ps_async.value.reference_id == seen_ps_refs[-1]

    # 6. Flutterwave (sync & async): auto-generated tx_ref/reference preserved on 503
    seen_flw_refs: list[str] = []

    def flw_fail_503(req: httpx.Request) -> httpx.Response:
        body = _json.loads(req.content.decode())
        seen_flw_refs.append(body.get("tx_ref") or body.get("reference"))
        return httpx.Response(
            503, json={"status": "error", "message": "Rail maintenance"}
        )

    flw_cfg = FlutterwaveConfig(
        secret_key="FLWSECK_TEST-123",
        default_customer_email="buyer@example.com",
        default_account_bank="044",
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(flw_fail_503),
            base_url="https://api.flutterwave.com",
        ) as raw_flw,
        FlutterwaveClient(flw_cfg, client=raw_flw) as fc,
        pytest.raises(PyMomoSDKServerError) as exc_flw_sync,
    ):
        fc.create_payment("100", "UGX", "256771234567")
    assert exc_flw_sync.value.reference_id == seen_flw_refs[-1]

    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(flw_fail_503),
            base_url="https://api.flutterwave.com",
        ) as raw_flwa,
        AsyncFlutterwaveClient(flw_cfg, client=raw_flwa) as afc,
    ):
        with pytest.raises(PyMomoSDKServerError) as exc_flw_async:
            await afc.create_transfer("100", "UGX", "0690000040")
    assert exc_flw_async.value.reference_id == seen_flw_refs[-1]

    # 7. Orange Money (sync & async): auto-generated order_id preserved on 500 AND token failure
    seen_or_refs: list[str] = []

    def orange_fail_500(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/oauth/v3/token":
            return httpx.Response(
                200, json={"access_token": "or-tok", "expires_in": 3600}
            )
        body = _json.loads(req.content.decode())
        seen_or_refs.append(body["order_id"])
        return httpx.Response(
            500, json={"code": "OM_DOWN", "description": "Orange switch error"}
        )

    or_cfg = OrangeMoneyConfig(
        client_id="oid",
        client_secret="osec",
        merchant_key="mk",
        return_url="https://merchant.example.com/ret",
        cancel_url="https://merchant.example.com/can",
        notif_url="https://merchant.example.com/not",
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(orange_fail_500),
            base_url="https://api.orange.com",
        ) as raw_or,
        OrangeMoneyClient(or_cfg, client=raw_or) as oc,
        pytest.raises(PyMomoSDKServerError) as exc_or_sync,
    ):
        oc.create_web_payment("500", "XOF")
    assert exc_or_sync.value.reference_id == seen_or_refs[-1]
    assert exc_or_sync.value.error_code == "OM_DOWN"

    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(orange_fail_500),
            base_url="https://api.orange.com",
        ) as raw_ora,
        AsyncOrangeMoneyClient(or_cfg, client=raw_ora) as aoc,
    ):
        with pytest.raises(PyMomoSDKServerError) as exc_or_async:
            await aoc.create_web_payment("500", "XOF")
    assert exc_or_async.value.reference_id == seen_or_refs[-1]


@pytest.mark.asyncio
async def test_router_failover_exhaustion_preserves_attempted_references_issue_115() -> (
    None
):
    """Verify PaymentRouter & AsyncPaymentRouter attach attempted_references when failover exhausts (#115)."""
    from py_momo_sdk.exceptions import AuthenticationError
    from py_momo_sdk.providers.models import (
        DisbursementRequest,
        PaymentRequest,
        ProviderCapabilities,
    )
    from py_momo_sdk.providers.router import AsyncPaymentRouter, PaymentRouter

    class _FailingSyncProvider:
        def __init__(self, name: str, err_ref: str) -> None:
            self.name = name
            self._err_ref = err_ref
            self.capabilities = ProviderCapabilities(
                provider_id=name,
                supports_collection=True,
                supports_disbursement=True,
                currencies=("UGX",),
            )

        def collect(self, request: PaymentRequest) -> object:
            raise AuthenticationError(
                f"{self.name} auth failed",
                reference_id=request.reference_id or self._err_ref,
                status_code=401,
                provider=self.name,
            )

        def disburse(self, request: DisbursementRequest) -> object:
            raise PyMomoSDKServerError(
                f"{self.name} 503",
                reference_id=request.reference_id or self._err_ref,
                status_code=503,
                provider=self.name,
            )

        def get_status(self, reference_id: str, *, kind: str = "collection") -> object:
            raise NotImplementedError

        def get_balance(
            self, *, kind: str = "collection", currency: str | None = None
        ) -> object:
            raise NotImplementedError

    router = PaymentRouter(
        [
            _FailingSyncProvider("rail_a", "ref-a-1"),  # type: ignore[list-item]
            _FailingSyncProvider("rail_b", "ref-b-1"),  # type: ignore[list-item]
        ],
        default_provider="rail_a",
    )

    with pytest.raises(AuthenticationError) as exc_col:
        router.collect(
            PaymentRequest(amount="1000", currency="UGX", payer_msisdn="256771234567"),
            fallback=True,
        )
    assert exc_col.value.reference_id == "ref-b-1"
    assert exc_col.value.attempted_references == [
        {"provider": "rail_a", "reference_id": "ref-a-1"},
        {"provider": "rail_b", "reference_id": "ref-b-1"},
    ]

    with pytest.raises(PyMomoSDKServerError) as exc_disb:
        router.disburse(
            DisbursementRequest(
                amount="1000", currency="UGX", payee_msisdn="256771234567"
            ),
            fallback=True,
            allow_ambiguous_write_fallback=True,
        )
    assert exc_disb.value.reference_id is not None
    assert len(exc_disb.value.attempted_references) == 2
    assert (
        exc_disb.value.attempted_references[0]["reference_id"]
        == exc_disb.value.reference_id
    )
    assert (
        exc_disb.value.attempted_references[1]["reference_id"]
        == exc_disb.value.reference_id
    )

    class _FailingAsyncProvider:
        def __init__(self, name: str, err_ref: str) -> None:
            self.name = name
            self._err_ref = err_ref
            self.capabilities = ProviderCapabilities(
                provider_id=name,
                supports_collection=True,
                supports_disbursement=True,
                currencies=("UGX",),
            )

        async def collect(self, request: PaymentRequest) -> object:
            raise AuthenticationError(
                f"{self.name} auth failed",
                reference_id=request.reference_id or self._err_ref,
                status_code=401,
                provider=self.name,
            )

        async def disburse(self, request: DisbursementRequest) -> object:
            raise PyMomoSDKServerError(
                f"{self.name} 503",
                reference_id=request.reference_id or self._err_ref,
                status_code=503,
                provider=self.name,
            )

        async def get_status(
            self, reference_id: str, *, kind: str = "collection"
        ) -> object:
            raise NotImplementedError

        async def get_balance(
            self, *, kind: str = "collection", currency: str | None = None
        ) -> object:
            raise NotImplementedError

    arouter = AsyncPaymentRouter(
        [
            _FailingAsyncProvider("arail_a", "aref-a"),  # type: ignore[list-item]
            _FailingAsyncProvider("arail_b", "aref-b"),  # type: ignore[list-item]
        ],
        default_provider="arail_a",
    )

    with pytest.raises(AuthenticationError) as exc_acol:
        await arouter.collect(
            PaymentRequest(amount="1000", currency="UGX", payer_msisdn="256771234567"),
            fallback=True,
        )
    assert exc_acol.value.reference_id == "aref-b"
    assert exc_acol.value.attempted_references == [
        {"provider": "arail_a", "reference_id": "aref-a"},
        {"provider": "arail_b", "reference_id": "aref-b"},
    ]

    with pytest.raises(PyMomoSDKServerError) as exc_adisb:
        await arouter.disburse(
            DisbursementRequest(
                amount="1000", currency="UGX", payee_msisdn="256771234567"
            ),
            fallback=True,
            allow_ambiguous_write_fallback=True,
        )
    assert exc_adisb.value.reference_id is not None
    assert len(exc_adisb.value.attempted_references) == 2
