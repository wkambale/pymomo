from __future__ import annotations

import base64
import hashlib
import hmac
import json
import socket
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from py_momo_sdk import (
    AirtelClient,
    AirtelConfig,
    AirtelMoneyProvider,
    AsyncAirtelClient,
    AsyncAirtelMoneyProvider,
    AsyncMtnMomoProvider,
    AsyncPaymentRouter,
    AsyncPyMomoSDK,
    DisbursementRequest,
    MtnMomoProvider,
    NormalizedStatus,
    PaymentRequest,
    PaymentResult,
    PaymentRouter,
    ProductConfig,
    ProviderCapabilities,
    PyMomoSDK,
    PyMomoSDKConfig,
    RequestTelemetryEvent,
    WebhookTelemetryEvent,
    WebhookVerificationError,
    create_asgi_webhook_verifier,
    create_mock_server,
    encrypt_airtel_pin,
    start_mock_server_thread,
    verify_django_webhook_request,
    verify_raw_webhook_request,
    verify_static_token_webhook_request,
)
from py_momo_sdk._async.airtel.auth import AsyncAirtelAuth
from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk._cli import app as cli_app
from py_momo_sdk.config import SANDBOX
from py_momo_sdk.exceptions import (
    AuthenticationError,
    PyMomoSDKError,
    PyMomoSDKServerError,
)
from py_momo_sdk.providers.models import BalanceResult

# ---------------------------------------------------------------------------
# 1. Optional-extra real integration tests (run in CI `integrations` job,
#    cleanly skipped via pytest.importorskip in minimal core test jobs)
# ---------------------------------------------------------------------------


def test_real_cryptography_rsa_pin_encryption_and_non_rsa_guard() -> None:
    """Verify encrypt_airtel_pin with a real RSA keypair and reject non-RSA EC keys."""
    crypto_padding = pytest.importorskip(
        "cryptography.hazmat.primitives.asymmetric.padding"
    )
    crypto_ec = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ec")
    crypto_rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")
    crypto_ser = pytest.importorskip("cryptography.hazmat.primitives.serialization")

    private_key = crypto_rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=crypto_ser.Encoding.PEM,
            format=crypto_ser.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )

    encrypted_b64 = encrypt_airtel_pin("4321", public_pem)
    ciphertext = base64.b64decode(encrypted_b64)
    decrypted = private_key.decrypt(ciphertext, crypto_padding.PKCS1v15())
    assert decrypted == b"4321"

    # Non-RSA public key (ECDSA P-256) must be rejected with TypeError
    ec_pub_pem = (
        crypto_ec.generate_private_key(crypto_ec.SECP256R1())
        .public_key()
        .public_bytes(
            encoding=crypto_ser.Encoding.PEM,
            format=crypto_ser.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    with pytest.raises(TypeError, match="RSA public key"):
        encrypt_airtel_pin("4321", ec_pub_pem)


def test_real_fastapi_starlette_webhook_verifier_end_to_end() -> None:
    """Verify create_asgi_webhook_verifier in a real FastAPI app with Request caching and HTTP 401."""
    fastapi = pytest.importorskip("fastapi")
    starlette_requests = pytest.importorskip("starlette.requests")
    testclient = pytest.importorskip("fastapi.testclient")

    secret = "whsec_real_fastapi"
    verifier = create_asgi_webhook_verifier(
        secret=secret,
        signature_header_name="X-Momo-Sig",
        http_error_status=401,
    )
    assert verifier.__annotations__["request"] is starlette_requests.Request

    app = fastapi.FastAPI()

    async def _webhook(
        request: Any,
        raw_body: bytes = fastapi.Depends(verifier),
    ) -> dict[str, Any]:
        # Downstream handler must still be able to read request.body() and request.json()
        re_read = await request.body()
        parsed = await request.json()
        return {
            "same_bytes": re_read == raw_body,
            "status": parsed["status"],
        }

    _webhook.__annotations__["request"] = starlette_requests.Request
    app.add_api_route("/webhook", _webhook, methods=["POST"])

    body = b'{"status":"SUCCESSFUL","amount":"1500"}'
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    client = testclient.TestClient(app)
    ok_resp = client.post(
        "/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Momo-Sig": f"sha256={sig}"},
    )
    assert ok_resp.status_code == 200
    assert ok_resp.json() == {"same_bytes": True, "status": "SUCCESSFUL"}

    bad_resp = client.post(
        "/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Momo-Sig": "sha256=deadbeef"},
    )
    assert bad_resp.status_code == 401


def test_real_django_request_factory_webhook_verifier_end_to_end() -> None:
    """Verify verify_django_webhook_request with a real Django HttpRequest from RequestFactory."""
    django_conf = pytest.importorskip("django.conf")
    django_test = pytest.importorskip("django.test")

    if not django_conf.settings.configured:
        django_conf.settings.configure(
            SECRET_KEY="test-only-django-key",
            ALLOWED_HOSTS=["testserver", "localhost"],
        )

    secret = "whsec_real_django"
    body = b'{"event":"payment.settled","amount":"5000"}'
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    factory = django_test.RequestFactory()
    req = factory.post(
        "/webhooks/momo",
        data=body,
        content_type="application/json",
        HTTP_X_MOMO_SIG=sig,
        REMOTE_ADDR="10.0.0.42",
    )
    verified = verify_django_webhook_request(
        req,
        secret=secret,
        signature_header_name="X-Momo-Sig",
        allowed_networks=["10.0.0.0/8"],
    )
    assert verified == body

    bad_ip_req = factory.post(
        "/webhooks/momo",
        data=body,
        content_type="application/json",
        HTTP_X_MOMO_SIG=sig,
        REMOTE_ADDR="198.51.100.7",
    )
    with pytest.raises(WebhookVerificationError, match="not in allowed networks"):
        verify_django_webhook_request(
            bad_ip_req,
            secret=secret,
            signature_header_name="X-Momo-Sig",
            allowed_networks=["10.0.0.0/8"],
        )


# ---------------------------------------------------------------------------
# 2. MTN & Airtel unified providers (sync & async) coverage closure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mtn_provider_sync_and_async_full_surface(
    httpx_mock: HTTPXMock,
) -> None:
    """Exercise all sync MtnMomoProvider and AsyncMtnMomoProvider methods and context managers."""
    ref_c = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    ref_d = "c38b25e7-a9a3-4874-9cb3-671e6268f760"
    cfg = PyMomoSDKConfig(
        environment=SANDBOX,
        collection=ProductConfig("c-sub", ref_c, "c-key"),
        disbursement=ProductConfig("d-sub", ref_d, "d-key"),
    )

    # Sync MtnMomoProvider: get_status(kind="collection"), get_balance(currency="UGX"), context manager
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "c-tok",
            "token_type": "access_token",
            "expires_in": 3600,
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay/{ref_c}",
        json={"status": "SUCCESSFUL", "amount": "500", "currency": "UGX"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance/UGX",
        json={"availableBalance": "999.00", "currency": "UGX"},
    )
    with MtnMomoProvider(PyMomoSDK(cfg)) as sync_prov:
        st = sync_prov.get_status(ref_c, kind="collection")
        assert st.status == NormalizedStatus.SUCCEEDED
        bal = sync_prov.get_balance(currency="UGX")
        assert bal.available_balance == "999.00"
        assert bal.currency == "UGX"

    # AsyncMtnMomoProvider: collect, disburse, get_status (both kinds), get_balance (with & without currency), close/aclose
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "ac-tok",
            "token_type": "access_token",
            "expires_in": 3600,
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/token/",
        json={
            "access_token": "ad-tok",
            "token_type": "access_token",
            "expires_in": 3600,
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay",
        status_code=202,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/transfer",
        status_code=202,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay/{ref_c}",
        json={"status": "SUCCESSFUL", "amount": "100", "currency": "UGX"},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/transfer/{ref_d}",
        json={"status": "FAILED", "reason": "PAYEE_NOT_FOUND"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        json={"availableBalance": "123.00", "currency": "EUR"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/account/balance/UGX",
        json={"availableBalance": "456.00", "currency": "UGX"},
    )

    async with AsyncMtnMomoProvider(AsyncPyMomoSDK(cfg)) as ap:
        assert ap.capabilities.provider_id == "mtn_momo"
        c_res = await ap.collect(
            PaymentRequest(
                amount="100",
                currency="UGX",
                payer_msisdn="256771234567",
                reference_id=ref_c,
            )
        )
        assert c_res.reference_id == ref_c
        d_res = await ap.disburse(
            DisbursementRequest(
                amount="200",
                currency="UGX",
                payee_msisdn="256771234567",
                reference_id=ref_d,
            )
        )
        assert d_res.reference_id == ref_d
        assert (
            await ap.get_status(ref_c, kind="collection")
        ).status == NormalizedStatus.SUCCEEDED
        assert (
            await ap.get_status(ref_d, kind="disbursement")
        ).status == NormalizedStatus.FAILED
        assert (await ap.get_balance()).available_balance == "123.00"
        assert (
            await ap.get_balance(kind="disbursement", currency="UGX")
        ).available_balance == "456.00"
        await ap.close()


@pytest.mark.asyncio
async def test_airtel_provider_sync_and_async_full_surface(
    httpx_mock: HTTPXMock,
) -> None:
    """Exercise all sync AirtelMoneyProvider and AsyncAirtelMoneyProvider branches."""
    cfg = AirtelConfig(
        client_id="cid", client_secret="csec", country="UG", currency="UGX", pin="1234"
    )
    ref = "air-ref-92"

    # Sync AirtelMoneyProvider: get_status(collection), get_balance(currency), close, context manager
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "at1", "expires_in": 3600},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://openapiuat.airtel.africa/standard/v1/payments/{ref}",
        json={
            "status": {"code": "200", "message": "OK", "result_code": "00"},
            "data": {"transaction": {"id": ref, "status": "TS"}},
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/standard/v1/users/balance",
        json={
            "data": {
                "wallet": {
                    "msisdn": "256751234567",
                    "balance": "2500",
                    "currency": "UGX",
                    "status": "ACTIVE",
                }
            }
        },
    )
    with AirtelMoneyProvider(AirtelClient(cfg)) as sp:
        assert (
            sp.get_status(ref, kind="collection").status == NormalizedStatus.SUCCEEDED
        )
        assert sp.get_balance(currency="UGX").available_balance == "2500"
        with pytest.raises(
            ValueError, match="does not match configured Airtel currency"
        ):
            sp.get_balance(currency="KES")

    # AsyncAirtelMoneyProvider: collect, get_status(disbursement), get_balance(currency), close/aclose
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "at2", "expires_in": 3600},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/merchant/v1/payments/",
        json={"status": {"code": "200", "message": "Accepted", "result_code": "00"}},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://openapiuat.airtel.africa/standard/v1/disbursements/{ref}",
        json={
            "status": {"code": "200", "message": "OK", "result_code": "00"},
            "data": {"transaction": {"id": ref, "status": "TF"}},
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/standard/v1/users/balance",
        json={
            "data": {
                "wallet": {
                    "msisdn": "256751234567",
                    "balance": "3500",
                    "currency": "UGX",
                    "status": "ACTIVE",
                }
            }
        },
    )
    async with AsyncAirtelMoneyProvider(AsyncAirtelClient(cfg)) as ap:
        c_res = await ap.collect(
            PaymentRequest(
                amount="1000",
                currency="UGX",
                payer_msisdn="256751234567",
                reference_id=ref,
            )
        )
        assert c_res.reference_id == ref
        assert (
            await ap.get_status(ref, kind="disbursement")
        ).status == NormalizedStatus.FAILED
        assert (await ap.get_balance(currency="UGX")).available_balance == "3500"
        await ap.close()


# ---------------------------------------------------------------------------
# 3. _async/airtel/auth.py & _async/airtel/client.py error & retry coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_airtel_auth_and_client_edge_branches() -> None:
    """Cover AsyncAirtelAuth & AsyncAirtelClient errors, telemetry isolation, retries, and 401 refresh failure."""
    auth = AsyncAirtelAuth(
        "cid", "secret-val", "https://openapiuat.airtel.africa", max_response_bytes=64
    )
    assert "secret-val" not in str(auth)

    # Oversized Content-Length, invalid Content-Length, TimeoutException, RequestError in AsyncAirtelAuth
    def _auth_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=b"x" * 128)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_auth_handler),
        base_url="https://openapiuat.airtel.africa",
    ) as raw_c:
        with pytest.raises(PyMomoSDKError, match="maximum allowed size"):
            await auth.get_token(raw_c)
        with (
            patch.object(raw_c, "send", side_effect=httpx.TimeoutException("t")),
            pytest.raises(PyMomoSDKError, match="timed out"),
        ):
            await auth.get_token(raw_c)
        with (
            patch.object(raw_c, "send", side_effect=httpx.RequestError("c")),
            pytest.raises(PyMomoSDKError, match="connection error"),
        ):
            await auth.get_token(raw_c)

    # AsyncAirtelClient invalid max_response_bytes
    cfg = AirtelConfig(
        client_id="cid",
        client_secret="csec",
        country="UG",
        currency="UGX",
        max_retries=1,
        retry_backoff=0.001,
    )
    with pytest.raises(ValueError, match="max_response_bytes"):
        AsyncAirtelClient(cfg, max_response_bytes=0)

    # Telemetry (including exploding hook), TimeoutException retry, RequestError retry, 503 retry, 401 refresh failure
    class _ExplodingTelemetry:
        def __init__(self) -> None:
            self.events: list[RequestTelemetryEvent] = []

        def on_request(self, event: RequestTelemetryEvent) -> None:
            self.events.append(event)
            raise RuntimeError("telemetry boom")

        def on_webhook(self, event: WebhookTelemetryEvent) -> None:
            del event

    attempts: dict[str, int] = {"t": 0, "c": 0, "s": 0}

    def _retry_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/oauth2/token":
            if attempts.get("fail_refresh"):
                return httpx.Response(500)
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if request.url.path == "/timeout-then-ok":
            attempts["t"] += 1
            if attempts["t"] == 1:
                raise httpx.ReadTimeout("timeout")
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/conn-then-fail":
            attempts["c"] += 1
            raise httpx.ConnectError("conn err")
        if request.url.path == "/503-then-ok":
            attempts["s"] += 1
            if attempts["s"] == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/401-bad-refresh":
            attempts["fail_refresh"] = 1
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True})

    hook = _ExplodingTelemetry()
    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(_retry_handler),
            base_url="https://openapiuat.airtel.africa",
        ) as raw_retry,
        AsyncAirtelClient(cfg, client=raw_retry, telemetry=hook) as client,
    ):
        assert (await client.request("GET", "/timeout-then-ok")).status_code == 200
        assert (await client.request("GET", "/503-then-ok")).status_code == 200
        with pytest.raises(PyMomoSDKError, match="connection error"):
            await client.request("GET", "/conn-then-fail")
        with pytest.raises(AuthenticationError, match="token refresh"):
            await client.request("GET", "/401-bad-refresh")
    assert len(hook.events) >= 6


# ---------------------------------------------------------------------------
# 4. Sync & Async PaymentRouter coverage closure
# ---------------------------------------------------------------------------


class _RouterDummySync:
    def __init__(
        self,
        name: str,
        *,
        fail_exc: Exception | None = None,
        supports_collection: bool = True,
        supports_disbursement: bool = True,
        supports_balance: bool = True,
        currencies: tuple[str, ...] = ("UGX",),
    ) -> None:
        self._name = name
        self._fail_exc = fail_exc
        self._caps = ProviderCapabilities(
            provider_id=name,
            supports_collection=supports_collection,
            supports_disbursement=supports_disbursement,
            supports_balance=supports_balance,
            currencies=currencies,
        )
        self.closed = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._caps

    def collect(self, request: PaymentRequest) -> PaymentResult:
        if self._fail_exc is not None:
            raise self._fail_exc
        return PaymentResult(
            provider=self._name,
            reference_id=request.reference_id or "sync-c",
            status=NormalizedStatus.PENDING,
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        if self._fail_exc is not None:
            raise self._fail_exc
        return PaymentResult(
            provider=self._name,
            reference_id=request.reference_id or "sync-d",
            status=NormalizedStatus.PENDING,
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
            provider=self._name, available_balance="10", currency=currency or "UGX"
        )

    def close(self) -> None:
        self.closed = True


class _RouterDummyAsync:
    def __init__(
        self,
        name: str,
        *,
        fail_exc: Exception | None = None,
        supports_collection: bool = True,
        supports_disbursement: bool = True,
        supports_balance: bool = True,
        currencies: tuple[str, ...] = ("UGX",),
        has_aclose: bool = True,
    ) -> None:
        self._name = name
        self._fail_exc = fail_exc
        self._caps = ProviderCapabilities(
            provider_id=name,
            supports_collection=supports_collection,
            supports_disbursement=supports_disbursement,
            supports_balance=supports_balance,
            currencies=currencies,
        )
        self.closed = False
        if not has_aclose:
            self.aclose = None  # type: ignore[assignment]

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._caps

    async def collect(self, request: PaymentRequest) -> PaymentResult:
        if self._fail_exc is not None:
            raise self._fail_exc
        return PaymentResult(
            provider=self._name,
            reference_id=request.reference_id or "async-c",
            status=NormalizedStatus.PENDING,
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        if self._fail_exc is not None:
            raise self._fail_exc
        return PaymentResult(
            provider=self._name,
            reference_id=request.reference_id or "async-d",
            status=NormalizedStatus.PENDING,
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
            provider=self._name, available_balance="20", currency=currency or "UGX"
        )

    async def aclose(self) -> None:
        self.closed = True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_sync_and_async_router_failover_capabilities_and_errors() -> None:
    """Close coverage gaps across PaymentRouter and AsyncPaymentRouter."""
    p_fail = _RouterDummySync("mtn_momo", fail_exc=PyMomoSDKServerError("503"))
    p_ok = _RouterDummySync("airtel_money")
    p_no_coll = _RouterDummySync(
        "disb_only", supports_collection=False, supports_balance=False
    )

    with PaymentRouter([p_fail, p_ok, p_no_coll]) as r:
        assert r.list_providers() == ["mtn_momo", "airtel_money", "disb_only"]
        with pytest.raises(PyMomoSDKError, match="not registered"):
            r.get("missing")
        with pytest.raises(PyMomoSDKError, match="not registered"):
            r.collect(
                PaymentRequest(
                    amount="10", currency="UGX", payer_msisdn="256771234567"
                ),
                provider="missing",
            )
        with pytest.raises(PyMomoSDKError, match="does not support collection"):
            r.collect(
                PaymentRequest(
                    amount="10", currency="UGX", payer_msisdn="256771234567"
                ),
                provider="disb_only",
            )
        with pytest.raises(PyMomoSDKError, match="does not support collection status"):
            r.get_status("ref-1", provider="disb_only", kind="collection")

        # Disbursement failover with allow_ambiguous_write_fallback=True
        d_res = r.disburse(
            DisbursementRequest(
                amount="50", currency="UGX", payee_msisdn="256771234567"
            ),
            fallback=True,
            allow_ambiguous_write_fallback=True,
        )
        assert d_res.provider == "airtel_money"
        assert d_res.raw["prior_failed_attempts"][0]["provider"] == "mtn_momo"

        # All providers fail -> re-raises last exception
        r_all_fail = PaymentRouter(
            [
                _RouterDummySync("mtn_momo", fail_exc=AuthenticationError("bad1")),
                _RouterDummySync("airtel_money", fail_exc=AuthenticationError("bad2")),
            ]
        )
        with pytest.raises(AuthenticationError, match="bad2"):
            r_all_fail.collect(
                PaymentRequest(
                    amount="10", currency="UGX", payer_msisdn="256771234567"
                ),
                fallback=True,
            )
        with pytest.raises(AuthenticationError, match="bad2"):
            r_all_fail.disburse(
                DisbursementRequest(
                    amount="10", currency="UGX", payee_msisdn="256771234567"
                ),
                fallback=True,
            )

    assert p_fail.closed and p_ok.closed

    # AsyncPaymentRouter full coverage
    ap_fail = _RouterDummyAsync("mtn_momo", fail_exc=PyMomoSDKServerError("503"))
    ap_ok = _RouterDummyAsync("airtel_money", has_aclose=False)
    ap_no_coll = _RouterDummyAsync("disb_only", supports_collection=False)

    async with AsyncPaymentRouter([ap_fail, ap_ok, ap_no_coll]) as ar:
        assert ar.list_providers() == ["mtn_momo", "airtel_money", "disb_only"]
        with pytest.raises(PyMomoSDKError, match="not registered"):
            await ar.collect(
                PaymentRequest(
                    amount="10", currency="UGX", payer_msisdn="256771234567"
                ),
                provider="missing",
            )
        with pytest.raises(PyMomoSDKError, match="does not support collection"):
            await ar.collect(
                PaymentRequest(
                    amount="10", currency="UGX", payer_msisdn="256771234567"
                ),
                provider="disb_only",
            )
        with pytest.raises(PyMomoSDKError, match="No matching payment provider"):
            await ar.collect(
                PaymentRequest(amount="10", currency="USD", payer_msisdn="256771234567")
            )

        ac_res = await ar.collect(
            PaymentRequest(amount="50", currency="UGX", payer_msisdn="256771234567"),
            fallback=True,
            allow_ambiguous_write_fallback=True,
        )
        assert ac_res.provider == "airtel_money"
        assert ac_res.raw["prior_failed_attempts"][0]["provider"] == "mtn_momo"

        ad_res = await ar.disburse(
            DisbursementRequest(
                amount="50", currency="UGX", payee_msisdn="256771234567"
            ),
            fallback=True,
            allow_ambiguous_write_fallback=True,
        )
        assert ad_res.provider == "airtel_money"
        assert ad_res.raw["prior_failed_attempts"][0]["provider"] == "mtn_momo"

        assert (
            await ar.get_balance(provider="airtel_money", currency="UGX")
        ).currency == "UGX"
        await ar.close()

        # All async providers fail
        ar_fail = AsyncPaymentRouter(
            [
                _RouterDummyAsync("mtn_momo", fail_exc=AuthenticationError("a1")),
                _RouterDummyAsync("airtel_money", fail_exc=AuthenticationError("a2")),
            ]
        )
        with pytest.raises(AuthenticationError, match="a2"):
            await ar_fail.collect(
                PaymentRequest(
                    amount="10", currency="UGX", payer_msisdn="256771234567"
                ),
                fallback=True,
            )
        with pytest.raises(AuthenticationError, match="a2"):
            await ar_fail.disburse(
                DisbursementRequest(
                    amount="10", currency="UGX", payee_msisdn="256771234567"
                ),
                fallback=True,
            )

    assert ap_fail.closed and ap_ok.closed


# ---------------------------------------------------------------------------
# 5. MTN products sync & async missing methods (disbursement, collection, base)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mtn_products_missing_sync_and_async_endpoints(
    client: PyMomoSDK,
    async_client: AsyncPyMomoSDK,
    httpx_mock: HTTPXMock,
) -> None:
    """Cover sync get_deposit_status, get_refund_status, get_withdraw_status, balance_for_currency, and OAuth2 refresh."""
    ref = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    orig_ref = "c38b25e7-a9a3-4874-9cb3-671e6268f760"

    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/token/",
        json={
            "access_token": "d-tok",
            "token_type": "access_token",
            "expires_in": 3600,
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v2_0/deposit",
        status_code=202,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/disbursement/v2_0/deposit/{ref}",
        json={"status": "SUCCESSFUL", "amount": "100", "currency": "EUR"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v2_0/refund",
        status_code=202,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/disbursement/v2_0/refund/{ref}",
        json={"status": "SUCCESSFUL", "amount": "50", "currency": "EUR"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/account/balance/EUR",
        json={"availableBalance": "300.00", "currency": "EUR"},
    )

    assert (
        client.disbursement.deposit(
            "100", "EUR", "256771234567", "ext-d", reference_id=ref
        )
        == ref
    )
    assert client.disbursement.get_deposit_status(ref).is_successful()
    assert (
        client.disbursement.refund("50", "EUR", orig_ref, "ext-r", reference_id=ref)
        == ref
    )
    assert client.disbursement.get_refund_status(ref).is_successful()
    assert client.disbursement.get_balance_for_currency("EUR").currency == "EUR"

    # Collection sync: request_to_withdraw with explicit ref, get_withdraw_status, bc_authorize validation, oauth2 refresh
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "c-tok",
            "token_type": "access_token",
            "expires_in": 3600,
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v2_0/requesttowithdraw",
        status_code=202,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v2_0/requesttowithdraw/{ref}",
        json={"status": "PENDING"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/oauth2/token/",
        json={
            "access_token": "refreshed-user-tok",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )

    assert (
        client.collection.request_to_withdraw(
            "25", "EUR", "256771234567", "ext-w", reference_id=ref
        )
        == ref
    )
    assert client.collection.get_withdraw_status(ref).is_pending()
    with pytest.raises(ValueError, match="access_type"):
        client.collection.bc_authorize("256771234567", access_type="   ")
    with pytest.raises(ValueError, match="online"):
        client.collection.bc_authorize("256771234567", access_type="invalid")
    with pytest.raises(ValueError, match="refresh_token"):
        client.collection.create_oauth2_token(grant_type="refresh_token")
    refreshed = client.collection.create_oauth2_token(
        grant_type="refresh_token", refresh_token="rt-123"
    )
    assert refreshed.access_token == "refreshed-user-tok"

    # Async collection bc_authorize validation & oauth2 refresh grant
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/oauth2/token/",
        json={
            "access_token": "async-refreshed-tok",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    with pytest.raises(ValueError, match="login_hint"):
        await async_client.collection.bc_authorize("   ")
    with pytest.raises(ValueError, match="scope"):
        await async_client.collection.bc_authorize("256771234567", scope="   ")
    with pytest.raises(ValueError, match="access_type"):
        await async_client.collection.bc_authorize("256771234567", access_type="   ")
    with pytest.raises(ValueError, match="online"):
        await async_client.collection.bc_authorize("256771234567", access_type="bad")
    with pytest.raises(ValueError, match="refresh_token"):
        await async_client.collection.create_oauth2_token(grant_type="refresh_token")
    async_refreshed = await async_client.collection.create_oauth2_token(
        grant_type="refresh_token", refresh_token="rt-async-123"
    )
    assert async_refreshed.access_token == "async-refreshed-tok"


# ---------------------------------------------------------------------------
# 6. frameworks.py, _async/http.py, mock_server.py, and _cli.py coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frameworks_and_async_http_remaining_branches() -> None:
    """Cover remaining header-extraction, validation, and ASGI/Django error paths in frameworks.py."""
    secret = "whsec_branches"
    body = b'{"ok":true}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    # .raw invalid entry
    class _BadRawHeaders:
        def __init__(self) -> None:
            self.raw = [("not-bytes", "val")]

    with pytest.raises(WebhookVerificationError, match="Invalid webhook header entry"):
        verify_raw_webhook_request(
            raw_body=body,
            headers=_BadRawHeaders(),  # type: ignore[arg-type]
            signature_header_name="X-Sig",
            secret=secret,
        )

    # .multi_items() valid, duplicate, and invalid entry
    class _MultiItemsHeaders:
        def __init__(self, pairs: list[tuple[Any, Any]]) -> None:
            self._pairs = pairs

        def multi_items(self) -> list[tuple[Any, Any]]:
            return self._pairs

    verify_raw_webhook_request(
        raw_body=body,
        headers=_MultiItemsHeaders([("X-Sig", sig)]),  # type: ignore[arg-type]
        signature_header_name="X-Sig",
        secret=secret,
    )
    with pytest.raises(WebhookVerificationError, match="Duplicate"):
        verify_raw_webhook_request(
            raw_body=body,
            headers=_MultiItemsHeaders([("X-Sig", sig), ("x-sig", sig)]),  # type: ignore[arg-type]
            signature_header_name="X-Sig",
            secret=secret,
        )
    with pytest.raises(WebhookVerificationError, match="Invalid webhook header entry"):
        verify_raw_webhook_request(
            raw_body=body,
            headers=_MultiItemsHeaders([(123, sig)]),  # type: ignore[arg-type]
            signature_header_name="X-Sig",
            secret=secret,
        )

    # .getlist() valid, missing (KeyError), duplicate, non-str
    class _GetListHeaders:
        def __init__(self, values: list[Any], *, raise_key_error: bool = False) -> None:
            self._values = values
            self._raise_key_error = raise_key_error

        def getlist(self, name: str) -> list[Any]:
            del name
            if self._raise_key_error:
                raise KeyError("missing")
            return self._values

    verify_raw_webhook_request(
        raw_body=body,
        headers=_GetListHeaders([sig]),  # type: ignore[arg-type]
        signature_header_name="X-Sig",
        secret=secret,
    )
    with pytest.raises(WebhookVerificationError):
        verify_raw_webhook_request(
            raw_body=body,
            headers=_GetListHeaders([], raise_key_error=True),  # type: ignore[arg-type]
            signature_header_name="X-Sig",
            secret=secret,
        )
    with pytest.raises(WebhookVerificationError, match="Duplicate"):
        verify_raw_webhook_request(
            raw_body=body,
            headers=_GetListHeaders([sig, sig]),  # type: ignore[arg-type]
            signature_header_name="X-Sig",
            secret=secret,
        )
    with pytest.raises(WebhookVerificationError, match="Invalid webhook header value"):
        verify_raw_webhook_request(
            raw_body=body,
            headers=_GetListHeaders([12345]),  # type: ignore[arg-type]
            signature_header_name="X-Sig",
            secret=secret,
        )

    # Non-mapping headers, missing remote_ip, non-bytes raw_body, oversized raw_body
    with pytest.raises(WebhookVerificationError, match="Invalid webhook headers"):
        verify_raw_webhook_request(
            raw_body=body,
            headers=object(),  # type: ignore[arg-type]
            signature_header_name="X-Sig",
            secret=secret,
        )
    with pytest.raises(WebhookVerificationError, match="source IP address is required"):
        verify_raw_webhook_request(
            raw_body=body,
            headers={"X-Sig": sig},
            signature_header_name="X-Sig",
            secret=secret,
            allowed_networks=["10.0.0.0/8"],
        )
    with pytest.raises(WebhookVerificationError, match="must be bytes"):
        verify_raw_webhook_request(
            raw_body="not-bytes",  # type: ignore[arg-type]
            headers={"X-Sig": sig},
            signature_header_name="X-Sig",
            secret=secret,
        )
    with pytest.raises(WebhookVerificationError, match="maximum allowed size"):
        verify_raw_webhook_request(
            raw_body=b"x" * 100,
            headers={"X-Sig": sig},
            signature_header_name="X-Sig",
            secret=secret,
            max_body_bytes=10,
        )
    with pytest.raises(WebhookVerificationError, match="source IP address is required"):
        verify_static_token_webhook_request(
            headers={"verif-hash": "tok"},
            token_header_name="verif-hash",
            expected_token="tok",
            allowed_networks=["10.0.0.0/8"],
        )

    # ASGI verifier: missing client host, body() fallback ClientDisconnect & oversized body
    asgi_v = create_asgi_webhook_verifier(
        secret=secret,
        signature_header_name="X-Sig",
        allowed_networks=["10.0.0.0/8"],
        max_body_bytes=16,
    )

    class _BodyOnlyReq:
        def __init__(
            self,
            payload: bytes,
            headers: dict[str, str],
            host: str | None = "10.0.0.1",
            disconnect: bool = False,
        ) -> None:
            self._payload = payload
            self.headers = headers
            self.client = SimpleNamespace(host=host) if host is not None else None
            self._disconnect = disconnect

        async def body(self) -> bytes:
            if self._disconnect:

                class ClientDisconnect(Exception):
                    pass

                raise ClientDisconnect()
            return self._payload

    with pytest.raises(WebhookVerificationError, match="source IP address is required"):
        await asgi_v(_BodyOnlyReq(body, {"X-Sig": sig}, host=None))
    with pytest.raises(WebhookVerificationError, match="Client disconnected"):
        await asgi_v(_BodyOnlyReq(body, {"X-Sig": sig}, disconnect=True))
    with pytest.raises(WebhookVerificationError, match="maximum allowed size"):
        await asgi_v(_BodyOnlyReq(b"x" * 64, {"X-Sig": sig}))

    # AsyncHttpClient invalid max_response_bytes, limits=, exploding telemetry hook
    with pytest.raises(ValueError, match="max_response_bytes"):
        AsyncHttpClient("https://example.com", 10.0, max_response_bytes=0)

    class _ExplodingReqHook:
        def on_request(self, event: RequestTelemetryEvent) -> None:
            del event
            raise RuntimeError("boom")

        def on_webhook(self, event: WebhookTelemetryEvent) -> None:
            del event

    async with AsyncHttpClient(
        "https://example.com",
        10.0,
        limits=httpx.Limits(max_connections=4),
        telemetry=_ExplodingReqHook(),
    ) as ahc:
        assert ahc._owns_client is True
        ahc._emit_telemetry("GET", "/x", 200, 0.0, 1, None)


def test_mock_server_remaining_routes_and_error_branches() -> None:
    """Exercise remaining mock_server validation, chunked-error, 501, and route branches."""
    with pytest.raises(ValueError, match="max_body_bytes"):
        create_mock_server("127.0.0.1", 0, max_body_bytes=0)
    with pytest.raises(ValueError, match="max_concurrent_requests"):
        create_mock_server("127.0.0.1", 0, max_concurrent_requests=0)

    # allow_non_loopback warning branch (bind to 127.0.0.1 isn't non-loopback; test with mock bind)
    srv, _state, _thread = start_mock_server_thread(
        "127.0.0.1", 0, default_status="PENDING", max_body_bytes=64
    )
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        # Unsupported Transfer-Encoding -> 501
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(
                b"POST /collection/v1_0/requesttopay HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nTransfer-Encoding: gzip\r\n"
                b"Connection: close\r\n\r\n"
            )
            assert b"501" in s.recv(4096)

        # Invalid hex chunk size -> 400
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(
                b"POST /collection/v1_0/requesttopay HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nTransfer-Encoding: chunked\r\n"
                b"Connection: close\r\n\r\nZZZZ\r\n"
            )
            assert b"400" in s.recv(4096)

        # Oversized chunk -> 413
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(
                b"POST /collection/v1_0/requesttopay HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nTransfer-Encoding: chunked\r\n"
                b"Connection: close\r\n\r\nFF\r\n" + b"a" * 255 + b"\r\n0\r\n\r\n"
            )
            assert b"413" in s.recv(4096)

        # Bad chunk CRLF -> 400
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(
                b"POST /collection/v1_0/requesttopay HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nTransfer-Encoding: chunked\r\n"
                b"Connection: close\r\n\r\n2\r\n{}XX0\r\n\r\n"
            )
            assert b"400" in s.recv(4096)

        # Truncated Content-Length -> 400
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(
                b"POST /collection/v1_0/requesttopay HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nContent-Length: 20\r\n"
                b"Connection: close\r\n\r\n{}"
            )
            s.shutdown(socket.SHUT_WR)
            assert b"400" in s.recv(4096)

        # Non-dict JSON -> 400
        assert (
            httpx.post(
                f"{base}/collection/v1_0/requesttopay", json=[1, 2, 3]
            ).status_code
            == 400
        )

        # Extra routes: bc-authorize, accountholder active/basicuserinfo, balances, remittance, airtel, mpesa b2c, paystack/flw/orange 404s
        assert httpx.post(f"{base}/collection/v1_0/bc-authorize").status_code == 200
        assert (
            httpx.get(
                f"{base}/collection/v1_0/accountholder/msisdn/256771234567/active"
            ).json()["result"]
            is True
        )
        assert (
            httpx.get(
                f"{base}/collection/v1_0/accountholder/msisdn/256771234567/basicuserinfo"
            ).json()["given_name"]
            == "Mock"
        )
        assert httpx.get(f"{base}/collection/v1_0/account/balance").status_code == 200
        assert (
            httpx.get(f"{base}/collection/v1_0/account/balance/UGX").json()["currency"]
            == "UGX"
        )
        assert httpx.get(f"{base}/v1_0/apiuser/missing").status_code == 404
        assert httpx.post(f"{base}/v1_0/apiuser/missing/apikey").status_code == 404
        assert (
            httpx.post(
                f"{base}/mpesa/b2c/v3/paymentrequest",
                json={"OriginatorConversationID": "oc-92"},
            ).json()["OriginatorConversationID"]
            == "oc-92"
        )
        assert (
            httpx.post(
                f"{base}/mpesa/stkpushquery/v1/query",
                json={"CheckoutRequestID": "missing"},
            ).status_code
            == 404
        )
        assert httpx.get(f"{base}/merchant/v2/wallets/balance/").status_code == 200
        assert httpx.get(f"{base}/standard/v1/payments/missing").status_code == 404
        assert httpx.get(f"{base}/v1/checkout/sessions/missing").status_code == 404
        assert httpx.get(f"{base}/v1/payout/missing").status_code == 404
        assert httpx.get(f"{base}/balance").status_code == 200
        assert httpx.get(f"{base}/transaction/verify/missing").status_code == 404
        assert httpx.get(f"{base}/v3/balances/UGX").json()["data"]["currency"] == "UGX"
        assert (
            httpx.get(
                f"{base}/v3/transactions/verify_by_reference?tx_ref=missing"
            ).status_code
            == 404
        )
        assert httpx.get(f"{base}/v3/transfers/missing").status_code == 404
        assert (
            httpx.post(
                f"{base}/orange-money-webpay/dev/v1/transactionstatus",
                json={"pay_token": "missing"},
            ).status_code
            == 404
        )
        assert httpx.post(f"{base}/unknown/post/route").status_code == 404
        assert httpx.get(f"{base}/unknown/get/route").status_code == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_cli_remittance_disbursement_and_timestamped_webhook(
    httpx_mock: HTTPXMock,
) -> None:
    """Cover CLI disbursement status, remittance transfer/status, and timestamped webhook verify."""
    runner = CliRunner()
    ref = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"

    # Disbursement status
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/token/",
        json={
            "access_token": "d-tok",
            "token_type": "access_token",
            "expires_in": 3600,
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/transfer/{ref}",
        json={"status": "SUCCESSFUL", "amount": "500", "currency": "EUR"},
    )
    d_st = runner.invoke(
        cli_app,
        [
            "disbursement",
            "status",
            ref,
            "--subscription-key",
            "sub",
            "--api-user",
            ref,
            "--api-key",
            "key",
        ],
    )
    assert d_st.exit_code == 0
    assert json.loads(d_st.stdout)["status"] == "SUCCESSFUL"

    # Remittance transfer & status
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/remittance/token/",
        json={
            "access_token": "r-tok",
            "token_type": "access_token",
            "expires_in": 3600,
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/remittance/v1_0/transfer",
        status_code=202,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/remittance/token/",
        json={
            "access_token": "r-tok2",
            "token_type": "access_token",
            "expires_in": 3600,
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/remittance/v1_0/transfer/{ref}",
        json={"status": "PENDING", "amount": "250", "currency": "EUR"},
    )
    r_tr = runner.invoke(
        cli_app,
        [
            "remittance",
            "transfer",
            "256771234567",
            "250",
            "EUR",
            "rem-1",
            "--reference-id",
            ref,
            "--subscription-key",
            "sub",
            "--api-user",
            ref,
            "--api-key",
            "key",
        ],
    )
    assert r_tr.exit_code == 0
    assert json.loads(r_tr.stdout)["reference_id"] == ref

    r_st = runner.invoke(
        cli_app,
        [
            "remittance",
            "status",
            ref,
            "--subscription-key",
            "sub",
            "--api-user",
            ref,
            "--api-key",
            "key",
        ],
    )
    assert r_st.exit_code == 0
    assert json.loads(r_st.stdout)["status"] == "PENDING"

    # Webhook verify --timestamped
    import time

    ts = int(time.time())
    secret = "whsec_cli_ts"
    body = '{"event":"paid"}'
    sig = hmac.new(
        secret.encode("utf-8"), f"{ts}.".encode() + body.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    wh = runner.invoke(
        cli_app,
        [
            "webhook",
            "verify",
            "--payload-file",
            "-",
            "--signature",
            f"t={ts},v1={sig}",
            "--secret",
            secret,
            "--timestamped",
        ],
        input=body,
    )
    assert wh.exit_code == 0
    assert json.loads(wh.stdout)["verified"] is True

    # Test CLI airtel encrypt-pin (with mocked encrypt_airtel_pin so it runs even without cryptography extra)
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=True) as pem_f:
        pem_f.write("-----BEGIN PUBLIC KEY-----\nDUMMY\n-----END PUBLIC KEY-----\n")
        pem_f.flush()
        with patch("py_momo_sdk._cli.encrypt_airtel_pin", return_value="ZW5jcnlwdGVk"):
            enc_res = runner.invoke(
                cli_app,
                [
                    "airtel",
                    "encrypt-pin",
                    "--public-key-file",
                    pem_f.name,
                    "--pin",
                    "1234",
                ],
            )
    assert enc_res.exit_code == 0
    assert json.loads(enc_res.stdout) == {"encrypted_pin": "ZW5jcnlwdGVk"}


@pytest.mark.asyncio
async def test_phase3_providers_async_mpesa_and_context_managers(
    httpx_mock: HTTPXMock,
) -> None:
    """Cover AsyncMpesaClient/AsyncMpesaProvider b2c/stk_query and provider context managers."""
    from py_momo_sdk import (
        AsyncFlutterwaveClient,
        AsyncFlutterwaveProvider,
        AsyncMpesaClient,
        AsyncMpesaProvider,
        AsyncOrangeMoneyClient,
        AsyncOrangeMoneyProvider,
        AsyncPaystackClient,
        AsyncPaystackProvider,
        AsyncWaveClient,
        AsyncWaveProvider,
        FlutterwaveClient,
        FlutterwaveConfig,
        FlutterwaveProvider,
        MpesaClient,
        MpesaConfig,
        MpesaProvider,
        OrangeMoneyClient,
        OrangeMoneyConfig,
        OrangeMoneyProvider,
        PaystackClient,
        PaystackConfig,
        PaystackProvider,
        WaveClient,
        WaveConfig,
        WaveProvider,
    )

    mp_cfg = MpesaConfig(
        consumer_key="ck",
        consumer_secret="cs",
        short_code="174379",
        passkey="pk",
        security_credential="sec-cred",
        callback_url="https://merchant.example.com/cb",
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials",
        json={"access_token": "mp-at", "expires_in": "3599"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/b2c/v3/paymentrequest",
        json={
            "ConversationID": "AG_async_1",
            "OriginatorConversationID": "oc-async-1",
            "ResponseCode": "0",
            "ResponseDescription": "Accepted",
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
        json={"ResultCode": "1032", "ResultDesc": "Cancelled by user"},
    )
    async with AsyncMpesaProvider(AsyncMpesaClient(mp_cfg)) as amp:
        b2c = await amp.disburse(
            DisbursementRequest(
                amount="500",
                currency="KES",
                payee_msisdn="254712345678",
                reference_id="oc-async-1",
            )
        )
        assert b2c.reference_id == "AG_async_1"
        q = await amp.get_status("ws_CO_99", kind="collection")
        assert q.status == NormalizedStatus.FAILED
        with pytest.raises(ValueError, match="KES only"):
            await amp.disburse(
                DisbursementRequest(
                    amount="500", currency="UGX", payee_msisdn="254712345678"
                )
            )
        await amp.close()

    with MpesaProvider(MpesaClient(mp_cfg)) as smp:
        assert smp.name == "mpesa"
    with WaveProvider(WaveClient(WaveConfig(api_key="wk"))) as swp:
        assert swp.name == "wave"
    async with AsyncWaveProvider(AsyncWaveClient(WaveConfig(api_key="wk"))) as awp:
        await awp.close()
    with PaystackProvider(PaystackClient(PaystackConfig(secret_key="sk"))) as spp:
        assert spp.name == "paystack"
    async with AsyncPaystackProvider(
        AsyncPaystackClient(PaystackConfig(secret_key="sk"))
    ) as app_:
        await app_.close()
    with FlutterwaveProvider(
        FlutterwaveClient(FlutterwaveConfig(secret_key="fk"))
    ) as sfp:
        assert sfp.name == "flutterwave"
    async with AsyncFlutterwaveProvider(
        AsyncFlutterwaveClient(FlutterwaveConfig(secret_key="fk"))
    ) as afp:
        await afp.close()
    om_cfg = OrangeMoneyConfig(client_id="id", client_secret="sec", merchant_key="mk")
    with OrangeMoneyProvider(OrangeMoneyClient(om_cfg)) as sop:
        assert sop.name == "orange_money"
    async with AsyncOrangeMoneyProvider(AsyncOrangeMoneyClient(om_cfg)) as aop:
        await aop.close()

    # Sync AirtelClient invalid max_response_bytes, exploding telemetry, RequestError retry, and 401 refresh failure
    air_cfg = AirtelConfig(
        client_id="cid",
        client_secret="csec",
        country="UG",
        currency="UGX",
        max_retries=1,
        retry_backoff=0.001,
    )
    with pytest.raises(ValueError, match="max_response_bytes"):
        AirtelClient(air_cfg, max_response_bytes=0)

    class _SyncExplodingHook:
        def on_request(self, event: RequestTelemetryEvent) -> None:
            del event
            raise RuntimeError("sync telemetry down")

        def on_webhook(self, event: WebhookTelemetryEvent) -> None:
            del event

    state: dict[str, int] = {"conn": 0, "fail_refresh": 0}

    def _sync_airtel_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/oauth2/token":
            if state["fail_refresh"]:
                return httpx.Response(500)
            return httpx.Response(
                200, json={"access_token": "stok", "expires_in": 3600}
            )
        if request.url.path == "/conn-err":
            state["conn"] += 1
            raise httpx.ConnectError("drop")
        if request.url.path == "/401-refresh-fail":
            state["fail_refresh"] = 1
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True})

    with (
        httpx.Client(
            transport=httpx.MockTransport(_sync_airtel_handler),
            base_url="https://openapiuat.airtel.africa",
        ) as raw_air,
        AirtelClient(air_cfg, client=raw_air, telemetry=_SyncExplodingHook()) as ac,
    ):
        assert ac.request("GET", "/ok").status_code == 200
        with pytest.raises(PyMomoSDKError, match="connection error"):
            ac.request("GET", "/conn-err")
        with pytest.raises(AuthenticationError, match="token refresh"):
            ac.request("GET", "/401-refresh-fail")

    # Provider DTO validators & predicates
    from pydantic import ValidationError

    from py_momo_sdk.providers.models import validate_operation_kind

    with pytest.raises(ValueError, match="kind"):
        validate_operation_kind("invalid")
    with pytest.raises(ValidationError):
        PaymentRequest(amount="10", currency="UGX", payer_msisdn="   ")
    with pytest.raises(ValidationError):
        DisbursementRequest(amount="10", currency="UGX", payee_msisdn="   ")
    pr = PaymentResult(
        provider="mtn_momo", reference_id="r1", status=NormalizedStatus.SUCCEEDED
    )
    assert pr.is_successful() is True
    assert pr.is_pending() is False
    assert pr.is_failed() is False
