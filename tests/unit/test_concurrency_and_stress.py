from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import patch

import httpx
import pytest

from py_momo_sdk import (
    AirtelClient,
    AirtelConfig,
    AsyncAirtelClient,
    AsyncPaymentRouter,
    AsyncPyMomoSDK,
    DisbursementRequest,
    NormalizedStatus,
    OrangeMoneyClient,
    OrangeMoneyConfig,
    PaymentRequest,
    PaymentResult,
    PaymentRouter,
    ProductConfig,
    ProviderCapabilities,
    PyMomoSDK,
    PyMomoSDKConfig,
    start_mock_server_thread,
)
from py_momo_sdk._async.airtel.auth import AsyncAirtelAuth
from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.airtel.auth import AirtelAuth
from py_momo_sdk.auth import TokenCache
from py_momo_sdk.config import SANDBOX
from py_momo_sdk.exceptions import (
    AuthenticationError,
    PyMomoSDKError,
    PyMomoSDKServerError,
)
from py_momo_sdk.http import HttpClient
from py_momo_sdk.providers.models import BalanceResult
from py_momo_sdk.providers.orange import _InMemoryOrangeContextStore


class _ChunkedSyncStream(httpx.SyncByteStream):
    """Streaming body with NO Content-Length header to exercise iter_bytes() caps."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        yield from self._chunks


class _ChunkedAsyncStream(httpx.AsyncByteStream):
    """Async streaming body with NO Content-Length header to exercise aiter_bytes() caps."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


def test_genuine_chunked_stream_max_response_bytes_sync() -> None:
    """Verify iter_bytes() enforces max_response_bytes when Content-Length is absent (sync)."""

    def _chunked_handler(request: httpx.Request) -> httpx.Response:
        del request
        resp = httpx.Response(
            200,
            stream=_ChunkedSyncStream([b"a" * 30, b"b" * 30, b"c" * 30]),
            headers={"Transfer-Encoding": "chunked"},
        )
        assert "content-length" not in resp.headers
        return resp

    # 1. Core sync HttpClient
    with (
        httpx.Client(
            transport=httpx.MockTransport(_chunked_handler),
            base_url="https://example.com",
        ) as raw_client,
        HttpClient(
            "https://example.com", 10.0, max_response_bytes=64, client=raw_client
        ) as hc,
        pytest.raises(PyMomoSDKError, match="maximum allowed size"),
    ):
        hc.request("GET", "/chunked-big", headers={})

    # 2. Sync AirtelAuth OAuth token stream cap (no Content-Length)
    with (
        httpx.Client(
            transport=httpx.MockTransport(_chunked_handler),
            base_url="https://openapiuat.airtel.africa",
        ) as raw_auth_client,
        pytest.raises(PyMomoSDKError, match="maximum allowed size"),
    ):
        auth = AirtelAuth(
            "cid", "csec", "https://openapiuat.airtel.africa", max_response_bytes=64
        )
        auth.get_token(raw_auth_client)

    # 3. Sync AirtelClient request stream cap (no Content-Length)
    def _airtel_chunked(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return _chunked_handler(request)

    cfg = AirtelConfig(
        client_id="cid", client_secret="csec", country="UG", currency="UGX"
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(_airtel_chunked),
            base_url="https://openapiuat.airtel.africa",
        ) as raw_airtel,
        AirtelClient(cfg, client=raw_airtel, max_response_bytes=64) as airtel_client,
        pytest.raises(PyMomoSDKError, match="maximum allowed size"),
    ):
        airtel_client.request("GET", "/chunked-big")


@pytest.mark.asyncio
async def test_genuine_chunked_stream_max_response_bytes_async() -> None:
    """Verify aiter_bytes() enforces max_response_bytes when Content-Length is absent (async)."""

    def _chunked_handler(request: httpx.Request) -> httpx.Response:
        del request
        resp = httpx.Response(
            200,
            stream=_ChunkedAsyncStream([b"x" * 30, b"y" * 30, b"z" * 30]),
            headers={"Transfer-Encoding": "chunked"},
        )
        assert "content-length" not in resp.headers
        return resp

    # 1. Core AsyncHttpClient
    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(_chunked_handler),
            base_url="https://example.com",
        ) as raw_client,
        AsyncHttpClient(
            "https://example.com", 10.0, max_response_bytes=64, client=raw_client
        ) as hc,
    ):
        with pytest.raises(PyMomoSDKError, match="maximum allowed size"):
            await hc.request("GET", "/chunked-big", headers={})

    # 2. AsyncAirtelAuth OAuth token stream cap (no Content-Length)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_chunked_handler),
        base_url="https://openapiuat.airtel.africa",
    ) as raw_auth_client:
        auth = AsyncAirtelAuth(
            "cid", "csec", "https://openapiuat.airtel.africa", max_response_bytes=64
        )
        with pytest.raises(PyMomoSDKError, match="maximum allowed size"):
            await auth.get_token(raw_auth_client)

    # 3. AsyncAirtelClient request stream cap (no Content-Length)
    def _airtel_chunked(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return _chunked_handler(request)

    cfg = AirtelConfig(
        client_id="cid", client_secret="csec", country="UG", currency="UGX"
    )
    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(_airtel_chunked),
            base_url="https://openapiuat.airtel.africa",
        ) as raw_airtel,
        AsyncAirtelClient(
            cfg, client=raw_airtel, max_response_bytes=64
        ) as airtel_client,
    ):
        with pytest.raises(PyMomoSDKError, match="maximum allowed size"):
            await airtel_client.request("GET", "/chunked-big")


def test_sync_thundering_herd_oauth_single_token_fetch() -> None:
    """Verify N=16 concurrent threads trigger exactly 1 OAuth token request for MTN and Airtel."""
    # 1. MTN sync PyMomoSDK
    mtn_token_calls = 0
    mtn_lock = threading.Lock()
    barrier = threading.Barrier(12)

    def _mtn_handler(request: httpx.Request) -> httpx.Response:
        nonlocal mtn_token_calls
        if request.url.path == "/collection/token/":
            time.sleep(0.02)
            with mtn_lock:
                mtn_token_calls += 1
            return httpx.Response(
                200,
                json={
                    "access_token": "mtn-herd-tok",
                    "token_type": "access_token",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(
            200, json={"availableBalance": "500.00", "currency": "UGX"}
        )

    cfg = PyMomoSDKConfig(
        environment=SANDBOX,
        collection=ProductConfig("sub", "e4d6934c-6fa1-49b4-9c59-bf558661b17c", "key"),
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(_mtn_handler),
            base_url="https://sandbox.momodeveloper.mtn.com",
        ) as raw_client,
        PyMomoSDK(cfg, client=raw_client) as sdk,
        ThreadPoolExecutor(max_workers=12) as pool,
    ):

        def _worker(_: int) -> str:
            barrier.wait()
            return sdk.collection.get_balance().available_balance

        results = list(pool.map(_worker, range(12)))
        assert results == ["500.00"] * 12
        assert mtn_token_calls == 1

    # 2. Airtel sync AirtelClient
    airtel_token_calls = 0
    airtel_lock = threading.Lock()
    airtel_barrier = threading.Barrier(12)

    def _airtel_handler(request: httpx.Request) -> httpx.Response:
        nonlocal airtel_token_calls
        if request.url.path == "/auth/oauth2/token":
            time.sleep(0.02)
            with airtel_lock:
                airtel_token_calls += 1
            return httpx.Response(
                200, json={"access_token": "airtel-herd-tok", "expires_in": 3600}
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "wallet": {
                        "msisdn": "256751234567",
                        "balance": "900.00",
                        "currency": "UGX",
                        "status": "ACTIVE",
                    }
                }
            },
        )

    airtel_cfg = AirtelConfig(
        client_id="cid", client_secret="csec", country="UG", currency="UGX"
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(_airtel_handler),
            base_url="https://openapiuat.airtel.africa",
        ) as raw_airtel,
        AirtelClient(airtel_cfg, client=raw_airtel) as client,
        ThreadPoolExecutor(max_workers=12) as pool,
    ):

        def _airtel_worker(_: int) -> str:
            airtel_barrier.wait()
            return client.disbursement.get_balance().data.wallet.balance

        airtel_results = list(pool.map(_airtel_worker, range(12)))
        assert airtel_results == ["900.00"] * 12
        assert airtel_token_calls == 1


@pytest.mark.asyncio
async def test_async_thundering_herd_oauth_single_token_fetch() -> None:
    """Verify N=16 concurrent coroutines trigger exactly 1 OAuth fetch for async MTN and Airtel."""
    # 1. MTN async
    mtn_token_calls = 0

    class _SlowAsyncMtnTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal mtn_token_calls
            if request.url.path == "/collection/token/":
                await asyncio.sleep(0.02)
                mtn_token_calls += 1
                return httpx.Response(
                    200,
                    json={
                        "access_token": "async-mtn-herd",
                        "token_type": "access_token",
                        "expires_in": 3600,
                    },
                )
            return httpx.Response(
                200, json={"availableBalance": "777.00", "currency": "UGX"}
            )

    cfg = PyMomoSDKConfig(
        environment=SANDBOX,
        collection=ProductConfig("sub", "e4d6934c-6fa1-49b4-9c59-bf558661b17c", "key"),
    )
    async with (
        httpx.AsyncClient(
            transport=_SlowAsyncMtnTransport(),
            base_url="https://sandbox.momodeveloper.mtn.com",
        ) as raw_client,
        AsyncPyMomoSDK(cfg, client=raw_client) as sdk,
    ):
        balances = await asyncio.gather(
            *(sdk.collection.get_balance() for _ in range(16))
        )
        assert [b.available_balance for b in balances] == ["777.00"] * 16
        assert mtn_token_calls == 1

    # 2. Airtel async (also covers double-checked cache hit in AsyncAirtelAuth.get_token)
    airtel_token_calls = 0

    class _SlowAsyncAirtelTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal airtel_token_calls
            if request.url.path == "/auth/oauth2/token":
                await asyncio.sleep(0.02)
                airtel_token_calls += 1
                return httpx.Response(
                    200, json={"access_token": "async-airtel-herd", "expires_in": 3600}
                )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "wallet": {
                            "msisdn": "256751234567",
                            "balance": "888.00",
                            "currency": "UGX",
                            "status": "ACTIVE",
                        }
                    }
                },
            )

    airtel_cfg = AirtelConfig(
        client_id="cid", client_secret="csec", country="UG", currency="UGX"
    )
    async with (
        httpx.AsyncClient(
            transport=_SlowAsyncAirtelTransport(),
            base_url="https://openapiuat.airtel.africa",
        ) as raw_airtel,
        AsyncAirtelClient(airtel_cfg, client=raw_airtel) as client,
    ):
        wallets = await asyncio.gather(
            *(client.disbursement.get_balance() for _ in range(16))
        )
        assert [w.data.wallet.balance for w in wallets] == ["888.00"] * 16
        assert airtel_token_calls == 1


@pytest.mark.asyncio
async def test_concurrent_401_refresh_cas_race_safety() -> None:
    """Verify concurrent 401 responses trigger CAS invalidation without evicting a fresh token."""
    cache = TokenCache()
    cache.set("collection", "stale-tok-1", 3600)
    refresh_count = 0
    refresh_lock = asyncio.Lock()

    async def _refresher() -> str:
        nonlocal refresh_count
        async with refresh_lock:
            existing = cache.get("collection")
            if existing is not None:
                return existing
            await asyncio.sleep(0.01)
            refresh_count += 1
            new_tok = f"fresh-tok-{refresh_count}"
            cache.set("collection", new_tok, 3600)
            return new_tok

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") == "Bearer stale-tok-1":
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True})

    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(_handler),
            base_url="https://sandbox.momodeveloper.mtn.com",
        ) as raw_client,
        AsyncHttpClient(
            "https://sandbox.momodeveloper.mtn.com", 10.0, client=raw_client
        ) as hc,
    ):
        responses = await asyncio.gather(
            *(
                hc.request(
                    "GET",
                    "/collection/v1_0/account/balance",
                    headers={"Authorization": "Bearer stale-tok-1"},
                    product_name="collection",
                    token_cache=cache,
                    token_refresher=_refresher,
                )
                for _ in range(8)
            )
        )
        assert all(r.status_code == 200 for r in responses)
        assert refresh_count == 1
        assert cache.get("collection") == "fresh-tok-1"


class _ConcurrentStubProvider:
    def __init__(self, name: str) -> None:
        self._name = name
        self.calls = 0
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self._name,
            supports_collection=True,
            supports_disbursement=True,
            supports_balance=True,
            currencies=("UGX", "KES"),
        )

    def collect(self, request: PaymentRequest) -> PaymentResult:
        with self._lock:
            self.calls += 1
        return PaymentResult(
            provider=self._name,
            reference_id=request.reference_id or f"ref-{self.calls}",
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        with self._lock:
            self.calls += 1
        return PaymentResult(
            provider=self._name,
            reference_id=request.reference_id or f"dref-{self.calls}",
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
        )

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        del kind
        return PaymentResult(
            provider=self._name,
            reference_id=reference_id,
            status=NormalizedStatus.SUCCEEDED,
        )

    def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        del kind
        return BalanceResult(
            provider=self._name,
            available_balance="1000",
            currency=currency or "UGX",
        )


class _ConcurrentAsyncStubProvider:
    def __init__(self, name: str) -> None:
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self._name,
            supports_collection=True,
            supports_disbursement=True,
            supports_balance=True,
            currencies=("UGX", "KES"),
        )

    async def collect(self, request: PaymentRequest) -> PaymentResult:
        await asyncio.sleep(0)
        self.calls += 1
        return PaymentResult(
            provider=self._name,
            reference_id=request.reference_id or f"aref-{self.calls}",
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        await asyncio.sleep(0)
        self.calls += 1
        return PaymentResult(
            provider=self._name,
            reference_id=request.reference_id or f"adref-{self.calls}",
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
        )

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        del kind
        return PaymentResult(
            provider=self._name,
            reference_id=reference_id,
            status=NormalizedStatus.SUCCEEDED,
        )

    async def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        del kind
        return BalanceResult(
            provider=self._name,
            available_balance="1000",
            currency=currency or "UGX",
        )


@pytest.mark.asyncio
async def test_concurrent_router_load_sync_and_async() -> None:
    """Stress-test PaymentRouter under threads and AsyncPaymentRouter under asyncio.gather."""
    mtn = _ConcurrentStubProvider("mtn_momo")
    airtel = _ConcurrentStubProvider("airtel_money")
    router = PaymentRouter([mtn, airtel])

    def _run_sync(idx: int) -> str:
        if idx % 5 == 0:
            router.register(_ConcurrentStubProvider(f"extra_{idx % 3}"))
            _ = router.list_providers()
        msisdn = "256771234567" if idx % 2 == 0 else "256751234567"
        res = router.collect(
            PaymentRequest(amount="500", currency="UGX", payer_msisdn=msisdn)
        )
        return res.provider

    with ThreadPoolExecutor(max_workers=8) as pool:
        providers_hit = list(pool.map(_run_sync, range(40)))
    assert providers_hit.count("mtn_momo") == 20
    assert providers_hit.count("airtel_money") == 20
    assert mtn.calls == 20
    assert airtel.calls == 20

    amtn = _ConcurrentAsyncStubProvider("mtn_momo")
    aairtel = _ConcurrentAsyncStubProvider("airtel_money")
    arouter = AsyncPaymentRouter([amtn, aairtel])

    async def _run_async(idx: int) -> str:
        msisdn = "256771234567" if idx % 2 == 0 else "256751234567"
        res = await arouter.collect(
            PaymentRequest(amount="500", currency="UGX", payer_msisdn=msisdn)
        )
        return res.provider

    async_hits = await asyncio.gather(*(_run_async(i) for i in range(40)))
    assert async_hits.count("mtn_momo") == 20
    assert async_hits.count("airtel_money") == 20


def test_mock_server_concurrent_load_and_503_saturation() -> None:
    """Stress-test mock_server under concurrent clients and verify 503 overload semaphore."""
    srv, _state, _thread = start_mock_server_thread(
        "127.0.0.1", 0, max_concurrent_requests=16
    )
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:

        def _hit(idx: int) -> tuple[int, int]:
            ref = f"00000000-0000-4000-8000-{idx:012d}"
            r1 = httpx.post(
                f"{base}/collection/v1_0/requesttopay",
                headers={"X-Reference-Id": ref},
                json={"amount": str(100 + idx), "currency": "UGX"},
                timeout=5.0,
            )
            r2 = httpx.get(
                f"{base}/collection/v1_0/requesttopay/{ref}",
                timeout=5.0,
            )
            return r1.status_code, r2.status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(_hit, range(24)))
        assert all(o == (202, 200) for o in outcomes)
    finally:
        srv.shutdown()
        srv.server_close()

    # Semaphore saturation: hold 1 slot with a slow raw socket, second socket gets 503
    sat_srv, _sat_state, _sat_thread = start_mock_server_thread(
        "127.0.0.1", 0, max_concurrent_requests=1, request_timeout=2.0
    )
    sat_port = sat_srv.server_address[1]
    try:
        slow_sock = socket.create_connection(("127.0.0.1", sat_port), timeout=5.0)
        try:
            # Start sending headers slowly without finishing the request so worker thread stays occupied
            slow_sock.sendall(
                b"POST /collection/v1_0/requesttopay HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Length: 50\r\n\r\n{"
            )
            # Poll briefly until worker holds semaphore, then verify 503
            got_503 = False
            for _ in range(20):
                time.sleep(0.02)
                with socket.create_connection(
                    ("127.0.0.1", sat_port), timeout=2.0
                ) as s2:
                    s2.sendall(
                        b"GET /collection/v1_0/account/balance HTTP/1.1\r\n"
                        b"Host: 127.0.0.1\r\nConnection: close\r\n\r\n"
                    )
                    resp = s2.recv(4096)
                if b"503 Service Unavailable" in resp:
                    got_503 = True
                    break
            assert got_503 is True
        finally:
            slow_sock.close()
    finally:
        sat_srv.shutdown()
        sat_srv.server_close()


def test_orange_context_store_bounded_eviction_stress() -> None:
    """Verify _InMemoryOrangeContextStore evicts FIFO and stays bounded under concurrent load."""
    store = _InMemoryOrangeContextStore(max_entries=16)

    def _writer(worker_id: int) -> None:
        for i in range(40):
            key = f"tok-{worker_id}-{i}"
            store.set(key, f"ord-{worker_id}-{i}", str(100 + i), "XOF")
            _ = store.get(key)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(_writer, range(6)))

    assert len(store._entries) <= 16

    # Deterministic FIFO eviction check
    fifo_store = _InMemoryOrangeContextStore(max_entries=2)
    fifo_store.set("p1", "o1", "100", "XOF")
    fifo_store.set("p2", "o2", "200", "XOF")
    fifo_store.set("p3", "o3", "300", "XOF")
    assert fifo_store.get("p1") is None
    assert fifo_store.get("p2") == ("o2", "200", "XOF")
    assert fifo_store.get("p3") == ("o3", "300", "XOF")

    # End-to-end OrangeMoneyClient with custom context_store
    def _om_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v3/token":
            return httpx.Response(
                200, json={"access_token": "om-t", "expires_in": 3600}
            )
        if request.url.path.endswith("/webpayment"):
            body = json.loads(request.content.decode())
            return httpx.Response(
                201,
                json={
                    "pay_token": f"pt-{body['order_id']}",
                    "payment_url": "https://webpay.orange.com/x",
                },
            )
        return httpx.Response(200, json={"status": "SUCCESS"})

    om_cfg = OrangeMoneyConfig(
        client_id="cid",
        client_secret="csec",
        merchant_key="mkey",
        return_url="https://merchant.example.com/ret",
        cancel_url="https://merchant.example.com/can",
        notif_url="https://merchant.example.com/notif",
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(_om_handler),
            base_url="https://api.orange.com",
        ) as raw_om,
        OrangeMoneyClient(om_cfg, client=raw_om, context_store=fifo_store) as om_client,
    ):
        res = om_client.create_web_payment(
            amount="500", currency="XOF", order_id="ord-live"
        )
        assert res["pay_token"] == "pt-ord-live"
        st = om_client.get_transaction_status(
            order_id="ord-live", amount="500", pay_token="pt-ord-live"
        )
        assert st["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_sync_and_async_429_retry_after_and_malformed_json_200() -> None:
    """Verify sync/async 429 Retry-After (numeric, >30s clamp, HTTP-date, exhausted) and malformed JSON 200."""
    slept_sync: list[float] = []
    future_date = format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=8), usegmt=True
    )
    sync_responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "1.5"}),
            httpx.Response(429, headers={"Retry-After": "120"}),
            httpx.Response(429, headers={"Retry-After": future_date}),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    with (
        patch("py_momo_sdk.http.time.sleep", side_effect=slept_sync.append),
        httpx.Client(
            transport=httpx.MockTransport(lambda _r: next(sync_responses)),
            base_url="https://example.com",
        ) as raw_c,
        HttpClient(
            "https://example.com",
            10.0,
            max_retries=3,
            retry_backoff=0.1,
            client=raw_c,
        ) as hc,
    ):
        resp = hc.request("GET", "/rate-limited", headers={})
        assert resp.status_code == 200
    assert 1.5 <= slept_sync[0] <= 1.8
    assert slept_sync[1] == pytest.approx(30.0)
    assert 3.0 <= slept_sync[2] <= 10.5

    # Exhausted 429 raises PyMomoSDKError with status 429
    with (
        patch("py_momo_sdk.http.time.sleep"),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _r: httpx.Response(429, headers={"Retry-After": "1"})
            ),
            base_url="https://example.com",
        ) as raw_exhausted,
        HttpClient(
            "https://example.com",
            10.0,
            max_retries=1,
            retry_backoff=0.01,
            client=raw_exhausted,
        ) as hc_ex,
        pytest.raises(PyMomoSDKError, match="429"),
    ):
        hc_ex.request("GET", "/always-429", headers={})

    # Async 429 Retry-After (numeric + >30s clamp) + RequestError retry + 401 refresh failure
    slept_async: list[float] = []

    async def _record_sleep(delay: float) -> None:
        slept_async.append(delay)

    async_calls = 0

    def _async_handler(request: httpx.Request) -> httpx.Response:
        nonlocal async_calls
        async_calls += 1
        if request.url.path == "/retry-err":
            if async_calls == 1:
                raise httpx.ConnectError("transient drop")
            if async_calls == 2:
                return httpx.Response(429, headers={"Retry-After": "99"})
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(401)

    with patch("py_momo_sdk._async.http.asyncio.sleep", side_effect=_record_sleep):
        async with (
            httpx.AsyncClient(
                transport=httpx.MockTransport(_async_handler),
                base_url="https://example.com",
            ) as raw_ac,
            AsyncHttpClient(
                "https://example.com",
                10.0,
                max_retries=2,
                retry_backoff=0.1,
                client=raw_ac,
            ) as ahc,
        ):
            r = await ahc.request("GET", "/retry-err", headers={})
            assert r.status_code == 200
            assert slept_async[1] == pytest.approx(30.0)

            async def _bad_refresher() -> str:
                raise ValueError("broken refresh")

            with pytest.raises(AuthenticationError, match="token refresh"):
                await ahc.request(
                    "GET",
                    "/need-auth",
                    headers={"Authorization": "Bearer expired"},
                    product_name="collection",
                    token_cache=TokenCache(),
                    token_refresher=_bad_refresher,
                )

    # Malformed HTML 200 on MTN product raises PyMomoSDKError (never json.JSONDecodeError)
    def _html_200_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/collection/token/":
            return httpx.Response(
                200,
                json={
                    "access_token": "tok",
                    "token_type": "access_token",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(200, text="<html>Gateway Error</html>")

    mtn_cfg = PyMomoSDKConfig(
        environment=SANDBOX,
        collection=ProductConfig("sub", "e4d6934c-6fa1-49b4-9c59-bf558661b17c", "key"),
    )
    with (
        httpx.Client(
            transport=httpx.MockTransport(_html_200_handler),
            base_url="https://sandbox.momodeveloper.mtn.com",
        ) as raw_html,
        PyMomoSDK(mtn_cfg, client=raw_html) as sdk,
        pytest.raises(PyMomoSDKError, match="invalid JSON"),
    ):
        sdk.collection.get_balance()

    # Keep PyMomoSDKServerError referenced for type parity
    assert issubclass(PyMomoSDKServerError, PyMomoSDKError)
