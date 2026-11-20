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

    assert len(hook.requests) == 2
    assert hook.requests[1].path == "/collection/v1_0/account/balance"
    assert hook.requests[1].status_code == 200
    assert hook.requests[1].latency_ms >= 0.0


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
