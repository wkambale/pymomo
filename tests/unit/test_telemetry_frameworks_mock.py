from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from py_momo_sdk import (
    PyMomoSDK,
    PyMomoSDKConfig,
    RequestTelemetryEvent,
    WebhookTelemetryEvent,
    WebhookVerificationError,
    create_asgi_webhook_verifier,
    start_mock_server_thread,
    verify_constant_time_token,
    verify_django_webhook_request,
)
from py_momo_sdk._cli import app
from py_momo_sdk.config import ProductConfig


class _CollectorHook:
    def __init__(self) -> None:
        self.requests: list[RequestTelemetryEvent] = []
        self.webhooks: list[WebhookTelemetryEvent] = []

    def on_request(self, event: RequestTelemetryEvent) -> None:
        self.requests.append(event)

    def on_webhook(self, event: WebhookTelemetryEvent) -> None:
        self.webhooks.append(event)


def test_telemetry_hook_emits_sanitized_request_events(httpx_mock: HTTPXMock) -> None:
    """Verify TelemetryHook captures request latency and status without secrets."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={"access_token": "tok", "token_type": "access_token", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        json={"availableBalance": "10.00", "currency": "EUR"},
        status_code=200,
    )

    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/accountholder/msisdn/256771234567/active",
        json={"result": True},
        status_code=200,
    )

    hook = _CollectorHook()
    cfg = PyMomoSDKConfig(
        environment="sandbox",
        telemetry=hook,
        collection=ProductConfig(
            subscription_key="super-secret-sub",
            api_user="e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            api_key="super-secret-key",
        ),
    )
    with PyMomoSDK(cfg) as client:
        client.collection.get_balance()
        assert client.collection.is_account_holder_active("256771234567") is True

    assert len(hook.requests) == 3
    assert hook.requests[1].path == "/collection/v1_0/account/balance"
    assert hook.requests[1].status_code == 200
    assert hook.requests[1].latency_ms >= 0.0
    assert "256771234567" not in hook.requests[2].path
    assert (
        hook.requests[2].path
        == "/collection/v1_0/accountholder/msisdn/<redacted>/active"
    )

    class _ExplodingHook:
        def on_request(self, event: RequestTelemetryEvent) -> None:
            raise RuntimeError("metrics backend down")

        def on_webhook(self, event: WebhookTelemetryEvent) -> None:
            raise RuntimeError("metrics backend down")

    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={"access_token": "tok", "token_type": "access_token", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay",
        status_code=202,
    )
    exploding_cfg = PyMomoSDKConfig(
        environment="sandbox",
        telemetry=_ExplodingHook(),
        collection=cfg.collection,
    )
    with PyMomoSDK(exploding_cfg) as client:
        ref = client.collection.request_to_pay(
            amount="100",
            currency="EUR",
            payer_msisdn="256771234567",
            external_id="ord-telemetry-safe",
        )
        assert len(ref) == 36


@pytest.mark.asyncio
async def test_framework_webhook_helpers_asgi_and_django() -> None:
    """Test FastAPI/Starlette ASGI and Django raw-body webhook verifiers."""
    secret = "whsec_framework_secret"
    body = b'{"status":"SUCCESSFUL","amount":"100.00"}'
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    verifier = create_asgi_webhook_verifier(
        secret=secret,
        signature_header_name="X-Momo-Sig",
        allowed_networks=["10.0.0.0/8"],
    )

    class _FakeRequest:
        def __init__(self, payload: bytes, headers: dict[str, str], host: str) -> None:
            self._payload = payload
            self.headers = headers
            self.client = SimpleNamespace(host=host)

        async def body(self) -> bytes:
            return self._payload

    verified = await verifier(
        _FakeRequest(body, {"x-momo-sig": f"sha256={sig}"}, "10.1.2.3")
    )
    assert verified == body

    with pytest.raises(WebhookVerificationError):
        await verifier(_FakeRequest(body, {"x-momo-sig": f"sha256={sig}"}, "192.0.2.1"))

    django_req = SimpleNamespace(
        body=body,
        headers={"X-Momo-Sig": sig},
        META={"REMOTE_ADDR": "10.0.0.5"},
    )
    assert (
        verify_django_webhook_request(
            django_req,
            secret=secret,
            signature_header_name="X-Momo-Sig",
            allowed_networks=["10.0.0.0/8"],
        )
        == body
    )

    verify_constant_time_token("tok-123", "tok-123")
    with pytest.raises(WebhookVerificationError):
        verify_constant_time_token("wrong", "tok-123")
    with pytest.raises(WebhookVerificationError):
        verify_constant_time_token("é-non-ascii", "tok-123")

    # Blocked IP must fail BEFORE reading request.body()
    body_read_called = False

    class _ExplodingBodyRequest:
        def __init__(self, payload: bytes, headers: dict[str, str], host: str) -> None:
            self._payload = payload
            self.headers = headers
            self.client = SimpleNamespace(host=host)

        async def body(self) -> bytes:
            nonlocal body_read_called
            body_read_called = True
            return self._payload

    with pytest.raises(WebhookVerificationError, match="not in allowed networks"):
        await verifier(
            _ExplodingBodyRequest(b"x" * 1024, {"x-momo-sig": sig}, "192.0.2.99")
        )
    assert body_read_called is False

    # Max body bytes enforced on ASGI streaming & Django verifier
    small_verifier = create_asgi_webhook_verifier(
        secret=secret, signature_header_name="X-Momo-Sig", max_body_bytes=16
    )

    class _StreamingRequest:
        def __init__(self, chunks: list[bytes], headers: dict[str, str]) -> None:
            self._chunks = chunks
            self.headers = headers
            self.client = SimpleNamespace(host="10.0.0.1")

        async def stream(self):  # type: ignore[no-untyped-def]
            for ch in self._chunks:
                yield ch

    with pytest.raises(WebhookVerificationError, match="maximum allowed size"):
        await small_verifier(
            _StreamingRequest([b"0123456789", b"0123456789"], {"x-momo-sig": sig})
        )
    with pytest.raises(WebhookVerificationError, match="maximum allowed size"):
        verify_django_webhook_request(
            SimpleNamespace(
                body=b"01234567890123456789", headers={"X-Momo-Sig": sig}, META={}
            ),
            secret=secret,
            signature_header_name="X-Momo-Sig",
            max_body_bytes=16,
        )

    # Duplicate signature headers rejected
    class _DupHeaders:
        def items(self) -> list[tuple[str, str]]:
            return [("X-Momo-Sig", sig), ("x-momo-sig", sig)]

    from py_momo_sdk.frameworks import verify_raw_webhook_request

    with pytest.raises(WebhookVerificationError, match="Duplicate"):
        verify_raw_webhook_request(
            raw_body=body,
            headers=_DupHeaders(),  # type: ignore[arg-type]
            signature_header_name="X-Momo-Sig",
            secret=secret,
        )

    # Timestamped mode, Content-Length bounds, empty tokens, and http_error_status fallback
    ts_sig = hmac.new(
        secret.encode(), b"1700000000." + body, hashlib.sha256
    ).hexdigest()
    with pytest.raises(WebhookVerificationError):
        verify_raw_webhook_request(
            raw_body=body,
            headers={"X-Momo-Sig": f"t=1700000000,v1={ts_sig}"},
            signature_header_name="X-Momo-Sig",
            secret=secret,
            timestamped=True,
        )
    with pytest.raises(ValueError, match="max_body_bytes"):
        create_asgi_webhook_verifier(secret=secret, max_body_bytes=0)
    with pytest.raises(WebhookVerificationError):
        verify_constant_time_token("", "tok")
    with pytest.raises(WebhookVerificationError):
        verify_constant_time_token("tok", "")
    err_verifier = create_asgi_webhook_verifier(
        secret=secret, signature_header_name="X-Momo-Sig", http_error_status=401
    )
    with pytest.raises(WebhookVerificationError):
        await err_verifier(
            _FakeRequest(body, {"content-length": "99999999"}, "10.0.0.1")
        )
    with pytest.raises(WebhookVerificationError):
        await err_verifier(
            _FakeRequest(body, {"content-length": "invalid"}, "10.0.0.1")
        )

    # WebhookTelemetryEvent emitted on pass and fail across framework verifiers
    wh_hook = _CollectorHook()
    verify_raw_webhook_request(
        raw_body=body,
        headers={"X-Momo-Sig": sig},
        signature_header_name="X-Momo-Sig",
        secret=secret,
        telemetry=wh_hook,
        provider="paystack",
    )
    with pytest.raises(WebhookVerificationError):
        verify_raw_webhook_request(
            raw_body=body,
            headers={"X-Momo-Sig": "bad"},
            signature_header_name="X-Momo-Sig",
            secret=secret,
            telemetry=wh_hook,
            provider="paystack",
        )
    assert len(wh_hook.webhooks) == 2
    assert wh_hook.webhooks[0] == WebhookTelemetryEvent(
        provider="paystack", verified=True, reason=None
    )
    assert wh_hook.webhooks[1].provider == "paystack"
    assert wh_hook.webhooks[1].verified is False
    assert wh_hook.webhooks[1].reason is not None

    # Empty X-Reference-Id must NOT be treated as retryable
    from py_momo_sdk.http import _is_retryable_request
    from py_momo_sdk.providers.mpesa import MpesaTokenResponse
    from py_momo_sdk.providers.orange import OrangeTokenResponse

    assert _is_retryable_request("POST", {"X-Reference-Id": "   "}) is False
    assert _is_retryable_request("POST", {"x-reference-id": "req-1"}) is True
    mtok = MpesaTokenResponse(access_token="sec-mpesa-tok", expires_in="3599")
    otok = OrangeTokenResponse(access_token="sec-orange-tok", expires_in="3600")  # type: ignore[arg-type]
    assert "sec-mpesa-tok" not in str(mtok)
    assert "sec-orange-tok" not in str(otok)
    from pydantic import ValidationError

    for bad_tok in ("", "bad\r\ntok"):
        with pytest.raises(ValidationError):
            MpesaTokenResponse(access_token=bad_tok, expires_in=3600)
        with pytest.raises(ValidationError):
            OrangeTokenResponse(access_token=bad_tok, expires_in=3600)
    for bad_exp in (True, -1, 1.5, "abc"):
        with pytest.raises(ValidationError):
            MpesaTokenResponse(access_token="ok", expires_in=bad_exp)  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            OrangeTokenResponse(access_token="ok", expires_in=bad_exp)  # type: ignore[arg-type]

    # ASGI & Django webhook telemetry emission + broken on_webhook isolation
    await create_asgi_webhook_verifier(
        secret=secret,
        signature_header_name="X-Momo-Sig",
        telemetry=wh_hook,
        provider="asgi_test",
    )(_FakeRequest(body, {"x-momo-sig": sig}, "10.0.0.1"))
    verify_django_webhook_request(
        django_req,
        secret=secret,
        signature_header_name="X-Momo-Sig",
        telemetry=wh_hook,
        provider="django_test",
    )
    assert len(wh_hook.webhooks) == 4


def test_local_mock_server_and_cli_carrier() -> None:
    """Test local mock gateway server end-to-end and CLI carrier command."""
    runner = CliRunner()
    cli_res = runner.invoke(app, ["carrier", "256771234567"])
    assert cli_res.exit_code == 0
    assert json.loads(cli_res.stdout) == {"country": "UG", "provider": "mtn_momo"}

    server, _state, _thread = start_mock_server_thread(
        port=0, default_status="SUCCESSFUL"
    )
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        tok = httpx.post(f"{base}/collection/token/", timeout=5.0)
        assert tok.status_code == 200
        assert tok.json()["access_token"] == "mock-access-token"

        ref = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
        rtp = httpx.post(
            f"{base}/collection/v1_0/requesttopay",
            headers={"X-Reference-Id": ref},
            json={"amount": "1500", "currency": "UGX", "externalId": "ord-1"},
            timeout=5.0,
        )
        assert rtp.status_code == 202

        st = httpx.get(f"{base}/collection/v1_0/requesttopay/{ref}", timeout=5.0)
        assert st.status_code == 200
        assert st.json()["status"] == "SUCCESSFUL"

        wave_res = httpx.post(
            f"{base}/v1/checkout/sessions",
            json={"amount": "500", "currency": "XOF"},
            timeout=5.0,
        )
        assert wave_res.status_code == 200
        sid = wave_res.json()["id"]
        assert (
            httpx.get(f"{base}/v1/checkout/sessions/{sid}", timeout=5.0).json()[
                "payment_status"
            ]
            == "succeeded"
        )
    finally:
        server.shutdown()
        server.server_close()

    # Non-loopback host, invalid status, oversized body, malformed JSON, FAILED mapping, and FIFO eviction
    from py_momo_sdk.mock_server import create_mock_server

    with pytest.raises(ValueError, match="non-loopback"):
        create_mock_server(host="0.0.0.0")  # nosec B104
    with pytest.raises(ValueError, match="default_status"):
        create_mock_server(default_status="BOGUS")

    fail_srv, fail_state, _ = start_mock_server_thread(
        port=0, default_status="FAILED", max_body_bytes=64, max_entries=2
    )
    fbase = f"http://127.0.0.1:{fail_srv.server_address[1]}"
    try:
        # Oversized body -> 413; invalid JSON -> 400; nested path -> 404
        assert (
            httpx.post(
                f"{fbase}/collection/v1_0/requesttopay",
                content=b"x" * 128,
                timeout=5.0,
            ).status_code
            == 413
        )
        assert (
            httpx.post(
                f"{fbase}/collection/v1_0/requesttopay",
                content=b"{bad-json",
                timeout=5.0,
            ).status_code
            == 400
        )
        assert (
            httpx.get(
                f"{fbase}/collection/v1_0/requesttopay/a/b", timeout=5.0
            ).status_code
            == 404
        )

        # Airtel with null transaction & FAILED -> TF
        assert (
            httpx.post(
                f"{fbase}/merchant/v1/payments/",
                json={"reference": "air-1", "transaction": None},
                timeout=5.0,
            ).status_code
            == 200
        )
        air_get = httpx.get(f"{fbase}/standard/v1/payments/air-1", timeout=5.0)
        assert air_get.json()["data"]["transaction"]["status"] == "TF"

        # Wave FAILED -> failed & FIFO eviction on max_entries=2
        for idx in range(3):
            httpx.post(
                f"{fbase}/v1/checkout/sessions",
                json={
                    "amount": "10",
                    "currency": "XOF",
                    "client_reference": f"r-{idx}",
                },
                timeout=5.0,
            )
        assert len(fail_state.wave_sessions) == 2
        assert "cos-1" not in fail_state.wave_sessions
        assert fail_state.wave_sessions["cos-3"]["payment_status"] == "failed"
    finally:
        fail_srv.shutdown()
        fail_srv.server_close()
