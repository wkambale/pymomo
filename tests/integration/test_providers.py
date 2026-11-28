from __future__ import annotations

import hashlib
import hmac

import pytest
from pytest_httpx import HTTPXMock

from py_momo_sdk import (
    AirtelConfig,
    AirtelMoneyProvider,
    AsyncAirtelClient,
    AsyncAirtelMoneyProvider,
    AsyncMtnMomoProvider,
    AsyncPaymentRouter,
    AsyncPyMomoSDK,
    AsyncWaveClient,
    AsyncWaveProvider,
    DisbursementRequest,
    MtnMomoProvider,
    NormalizedStatus,
    PaymentRequest,
    PaymentRouter,
    PyMomoSDK,
    PyMomoSDKConfig,
    PyMomoSDKError,
    WaveClient,
    WaveConfig,
    WaveProvider,
)
from py_momo_sdk.airtel.client import AirtelClient
from py_momo_sdk.config import ProductConfig
from py_momo_sdk.providers import discover_provider_plugins


def _mtn_config() -> PyMomoSDKConfig:
    return PyMomoSDKConfig(
        environment="sandbox",
        collection=ProductConfig(
            subscription_key="mtn-coll-sub",
            api_user="e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            api_key="mtn-coll-key",
        ),
        disbursement=ProductConfig(
            subscription_key="mtn-disb-sub",
            api_user="e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            api_key="mtn-disb-key",
        ),
    )


def _airtel_config() -> AirtelConfig:
    return AirtelConfig(
        client_id="airtel-id",
        client_secret="airtel-secret",
        country="UG",
        currency="UGX",
        pin="1234",
        environment="sandbox",
    )


def _wave_config() -> WaveConfig:
    return WaveConfig(
        api_key="wave_sn_prod_secret",
        webhook_secret="whsec_wave",
        success_url="https://callback.example.test/wave/success",
        error_url="https://callback.example.test/wave/error",
    )


def test_router_carrier_inference_and_fallback(httpx_mock: HTTPXMock) -> None:
    """Test PaymentRouter safe pre-flight fallback, ambiguous 5xx protection, and capability filtering."""
    from py_momo_sdk import OrangeMoneyClient, OrangeMoneyConfig, OrangeMoneyProvider
    from py_momo_sdk.exceptions import PyMomoSDKServerError

    ref = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    # 1. Ambiguous 503 on POST write must NOT fail over unless allow_ambiguous_write_fallback=True
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "mtn-tok",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay",
        status_code=503,
    )
    # 2. Pre-flight auth failure (401 on token endpoint) safely fails over to Airtel
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        status_code=401,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "airtel-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/merchant/v1/payments/",
        json={"status": {"code": "200", "message": "Accepted", "result_code": "DP008"}},
        status_code=200,
    )

    with (
        PyMomoSDK(_mtn_config()) as mtn_client,
        PyMomoSDK(_mtn_config()) as mtn_bad_auth,
        AirtelClient(_airtel_config()) as airtel_client,
        OrangeMoneyClient(
            OrangeMoneyConfig(client_id="cid", client_secret="sec", merchant_key="mk")
        ) as orange_client,
    ):
        router = PaymentRouter(
            [MtnMomoProvider(mtn_client), AirtelMoneyProvider(airtel_client)]
        )
        assert router.list_providers() == ["mtn_momo", "airtel_money"]

        req = PaymentRequest(
            amount="5000.00",
            currency="UGX",
            payer_msisdn="256771234567",
            external_id="order-1",
            reference_id=ref,
        )
        with pytest.raises(PyMomoSDKServerError):
            router.collect(req, fallback=True)

        # Safe failover on unambiguous pre-flight AuthenticationError
        router_pre = PaymentRouter(
            [MtnMomoProvider(mtn_bad_auth), AirtelMoneyProvider(airtel_client)]
        )
        result = router_pre.collect(req, fallback=True)
        assert result.provider == "airtel_money"
        assert result.reference_id == ref
        assert result.is_pending()

        # Capability & currency filtering + unknown default_provider validation
        with pytest.raises(PyMomoSDKError, match="Default provider is not registered"):
            PaymentRouter([MtnMomoProvider(mtn_client)], default_provider="nonexistent")
        orange_router = PaymentRouter([OrangeMoneyProvider(orange_client)])
        with pytest.raises(PyMomoSDKError, match="does not support disbursement"):
            orange_router.disburse(
                DisbursementRequest(
                    amount="100",
                    currency="XOF",
                    payee_msisdn="221771234567",
                ),
                provider="orange_money",
            )
        with pytest.raises(PyMomoSDKError, match="No matching payment provider"):
            orange_router.collect(req)


def test_wave_client_and_provider_sync(httpx_mock: HTTPXMock) -> None:
    """Test WaveClient, WaveProvider, and Wave webhook verification."""
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/checkout/sessions",
        json={
            "id": "cos-123",
            "amount": "1000",
            "currency": "XOF",
            "checkout_status": "open",
            "payment_status": "processing",
            "wave_launch_url": "https://pay.wave.com/c/cos-123",
            "client_reference": "order-wave-1",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/checkout/sessions/cos-123",
        json={
            "id": "cos-123",
            "amount": "1000",
            "currency": "XOF",
            "checkout_status": "complete",
            "payment_status": "succeeded",
            "client_reference": "order-wave-1",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/payout",
        json={
            "id": "pt-456",
            "receive_amount": "500",
            "currency": "XOF",
            "status": "succeeded",
            "client_reference": "payout-1",
            "transaction_id": "T_WAVE_456",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/balance",
        json={"amount": "25000", "currency": "XOF"},
        status_code=200,
    )

    cfg = _wave_config()
    assert "wave_sn_prod_secret" not in repr(cfg)

    with WaveClient(cfg) as wave_client:
        provider = WaveProvider(wave_client)
        assert provider.capabilities.supports_webhook_hmac is True

        col = provider.collect(
            PaymentRequest(
                amount="1000",
                currency="XOF",
                payer_msisdn="221761234567",
                external_id="order-wave-1",
            )
        )
        assert col.checkout_url == "https://pay.wave.com/c/cos-123"
        assert col.is_pending()

        st = provider.get_status("cos-123")
        assert st.status == NormalizedStatus.SUCCEEDED
        assert st.is_successful()

        disb = provider.disburse(
            DisbursementRequest(
                amount="500",
                currency="XOF",
                payee_msisdn="221761234567",
                external_id="payout-1",
            )
        )
        assert disb.is_successful()

        bal = provider.get_balance()
        assert bal.available_balance == "25000"
        assert bal.currency == "XOF"

        body = b'{"type":"checkout.session.completed"}'
        import time

        ts = int(time.time())
        sig = hmac.new(
            b"whsec_wave", f"{ts}".encode() + body, hashlib.sha256
        ).hexdigest()
        wave_client.verify_webhook(body, f"t={ts},v1={sig}")


@pytest.mark.asyncio
async def test_async_providers_and_router(httpx_mock: HTTPXMock) -> None:
    """Test AsyncPaymentRouter across AsyncMtnMomoProvider, AsyncAirtelMoneyProvider, AsyncWaveProvider."""
    ref = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "mtn-tok",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay/{ref}",
        json={
            "financialTransactionId": "fin-1",
            "externalId": "ext-1",
            "amount": "1000",
            "currency": "UGX",
            "status": "SUCCESSFUL",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/checkout/sessions",
        json={
            "id": "cos-async-1",
            "amount": "2000",
            "currency": "XOF",
            "payment_status": "processing",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/balance",
        json={"amount": "9000", "currency": "XOF"},
        status_code=200,
    )

    async with (
        AsyncPyMomoSDK(_mtn_config()) as mtn,
        AsyncAirtelClient(_airtel_config()) as airtel,
        AsyncWaveClient(_wave_config()) as wave,
    ):
        router = AsyncPaymentRouter(
            [
                AsyncMtnMomoProvider(mtn),
                AsyncAirtelMoneyProvider(airtel),
                AsyncWaveProvider(wave),
            ],
            custom_carrier_prefixes={"22176": ("SN", "wave")},
        )
        # Custom carrier prefix routes Senegal 22176 to Wave
        wave_res = await router.collect(
            PaymentRequest(
                amount="2000",
                currency="XOF",
                payer_msisdn="221761234567",
            )
        )
        assert wave_res.provider == "wave"
        assert wave_res.reference_id == "cos-async-1"

        mtn_status = await router.get_status(ref, provider="mtn_momo")
        assert mtn_status.is_successful()
        assert mtn_status.provider_transaction_id == "fin-1"

        wave_bal = await router.get_balance(provider="wave")
        assert wave_bal.available_balance == "9000"

        with pytest.raises(PyMomoSDKError, match="not registered"):
            router.get("unknown")


def test_discover_provider_plugins_returns_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify plugin discovery enforces allowlists, collision detection, and validation."""
    assert isinstance(discover_provider_plugins(), dict)
    with pytest.raises(TypeError, match="allowed_plugins"):
        discover_provider_plugins(allowed_plugins="not-a-set")

    loaded_calls: list[str] = []

    class _FakeEP:
        def __init__(self, name: str, fn: object) -> None:
            self.name = name
            self._fn = fn

        def load(self) -> object:
            loaded_calls.append(self.name)
            if isinstance(self._fn, Exception):
                raise self._fn
            return self._fn

    import py_momo_sdk.providers.router as router_mod

    # 1. Allowlist skips untrusted entry points BEFORE calling .load()
    monkeypatch.setattr(
        router_mod,
        "entry_points",
        lambda group: [
            _FakeEP("trusted", lambda: None),
            _FakeEP("untrusted", RuntimeError("must not run")),
        ],
    )
    res = discover_provider_plugins(allowed_plugins={"trusted"})
    assert list(res.keys()) == ["trusted"]
    assert loaded_calls == ["trusted"]

    # 2. Duplicate entry-point collision rejected
    monkeypatch.setattr(
        router_mod,
        "entry_points",
        lambda group: [_FakeEP("dup", lambda: None), _FakeEP("dup", lambda: None)],
    )
    with pytest.raises(PyMomoSDKError, match="Duplicate provider plugin"):
        discover_provider_plugins()

    # 3. Invalid object & load error rejected when strict=True, skipped when strict=False
    monkeypatch.setattr(
        router_mod,
        "entry_points",
        lambda group: [_FakeEP("bad_obj", 12345)],
    )
    with pytest.raises(PyMomoSDKError, match="not a valid PaymentProvider"):
        discover_provider_plugins(strict=True)
    assert discover_provider_plugins(strict=False) == {}

    monkeypatch.setattr(
        router_mod,
        "entry_points",
        lambda group: [_FakeEP("boom", RuntimeError("broken import"))],
    )
    with pytest.raises(PyMomoSDKError, match="Failed to load"):
        discover_provider_plugins(strict=True)
    assert discover_provider_plugins(strict=False) == {}


def test_mtn_and_airtel_providers_full_sync_methods(httpx_mock: HTTPXMock) -> None:
    """Test disburse, get_status, and get_balance on MtnMomoProvider and AirtelMoneyProvider."""
    ref = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    # MTN mocks
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/token/",
        json={
            "access_token": "mtn-d",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/transfer",
        status_code=202,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/transfer/{ref}",
        json={"status": "FAILED", "reason": "NOT_ENOUGH_FUNDS"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/account/balance",
        json={"availableBalance": "500.00", "currency": "UGX"},
        status_code=200,
    )
    # Airtel mocks
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "air-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/standard/v1/disbursements/",
        json={"status": {"code": "200", "message": "OK", "result_code": "DP009"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://openapiuat.airtel.africa/standard/v1/disbursements/{ref}",
        json={
            "status": {"code": "200", "message": "OK", "result_code": "00"},
            "data": {"transaction": {"id": ref, "status": "TS", "amount": "100"}},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/standard/v1/users/balance",
        json={
            "data": {
                "wallet": {
                    "msisdn": "256751234567",
                    "balance": "1200.00",
                    "currency": "UGX",
                    "status": "ACTIVE",
                }
            }
        },
        status_code=200,
    )

    with (
        PyMomoSDK(_mtn_config()) as mtn_client,
        AirtelClient(_airtel_config()) as airtel_client,
    ):
        router = PaymentRouter(
            [MtnMomoProvider(mtn_client), AirtelMoneyProvider(airtel_client)]
        )
        mtn_disb = router.disburse(
            DisbursementRequest(
                amount="100",
                currency="UGX",
                payee_msisdn="256771234567",
                reference_id=ref,
            )
        )
        assert mtn_disb.is_pending()
        mtn_st = router.get_status(ref, provider="mtn_momo", kind="disbursement")
        assert mtn_st.is_failed()
        assert (
            router.get_balance(
                provider="mtn_momo", kind="disbursement"
            ).available_balance
            == "500.00"
        )

        air_disb = router.disburse(
            DisbursementRequest(
                amount="100",
                currency="UGX",
                payee_msisdn="256751234567",
                reference_id=ref,
            )
        )
        assert air_disb.provider == "airtel_money"
        air_st = router.get_status(ref, provider="airtel_money", kind="disbursement")
        assert air_st.is_successful()
        assert (
            router.get_balance(provider="airtel_money").available_balance == "1200.00"
        )


@pytest.mark.asyncio
async def test_async_mtn_airtel_wave_disburse_and_status(
    httpx_mock: HTTPXMock,
) -> None:
    """Test async disburse, get_status, and get_balance across all three adapters."""
    ref = "c38b25e7-a9a3-4874-9cb3-671e6268f760"
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "air-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/standard/v1/disbursements/",
        json={"status": {"code": "200", "message": "OK", "result_code": "DP009"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://openapiuat.airtel.africa/standard/v1/payments/{ref}",
        json={
            "status": {"code": "200", "message": "Failed", "result_code": "DP008"},
            "data": {"transaction": {"id": ref, "status": "TF", "message": "Declined"}},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/standard/v1/users/balance",
        json={
            "data": {
                "wallet": {
                    "msisdn": "256751234567",
                    "balance": "4400.00",
                    "currency": "UGX",
                    "status": "ACTIVE",
                }
            }
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/payout",
        json={
            "id": "pt-async",
            "amount": "500",
            "currency": "XOF",
            "status": "succeeded",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/payout/pt-async",
        json={
            "id": "pt-async",
            "amount": "500",
            "currency": "XOF",
            "status": "succeeded",
        },
        status_code=200,
    )

    async with (
        AsyncPyMomoSDK(_mtn_config()) as mtn,
        AsyncAirtelClient(_airtel_config()) as airtel,
        AsyncWaveClient(_wave_config()) as wave,
    ):
        router = AsyncPaymentRouter(
            [
                AsyncMtnMomoProvider(mtn),
                AsyncAirtelMoneyProvider(airtel),
                AsyncWaveProvider(wave),
            ]
        )
        air_disb = await router.disburse(
            DisbursementRequest(
                amount="100",
                currency="UGX",
                payee_msisdn="256751234567",
                reference_id=ref,
            )
        )
        assert air_disb.provider == "airtel_money"
        air_st = await router.get_status(ref, provider="airtel_money")
        assert air_st.is_failed()
        assert (
            await router.get_balance(provider="airtel_money")
        ).available_balance == "4400.00"

        wave_disb = await router.disburse(
            DisbursementRequest(
                amount="500",
                currency="XOF",
                payee_msisdn="221761234567",
            ),
            provider="wave",
        )
        assert wave_disb.is_successful()
        wave_st = await router.get_status(
            "pt-async", provider="wave", kind="disbursement"
        )
        assert wave_st.is_successful()


@pytest.mark.asyncio
async def test_wave_live_protocol_and_webhook_fixes(httpx_mock: HTTPXMock) -> None:
    """Verify Issue #86: receive_amount, Wave-Signature no-dot format, no X-Reference-Id, error_url, and telemetry."""
    import json
    import time

    from py_momo_sdk import WebhookHandler, WebhookVerificationError
    from py_momo_sdk.providers.wave import WaveCheckoutSession, WavePayoutResponse
    from py_momo_sdk.telemetry import (
        RequestTelemetryEvent,
        TelemetryHook,
        WebhookTelemetryEvent,
    )

    # 1. WaveConfig rejects blank/whitespace webhook_secret
    with pytest.raises(ValueError, match="webhook_secret"):
        WaveConfig(api_key="wave_key", webhook_secret="   ")

    # 2. Live WavePayoutResponse with receive_amount + backward-compatible .amount
    live_payout = WavePayoutResponse.model_validate(
        {
            "id": "pt-185sewgm8100t",
            "currency": "XOF",
            "receive_amount": "5000",
            "status": "failed",
            "transaction_id": "T_WAVE_99",
            "when_completed": "2026-04-01T12:00:00Z",
            "payout_error": {"code": "insufficient-funds", "message": "Low balance"},
        }
    )
    assert live_payout.receive_amount == "5000"
    assert live_payout.amount == "5000"
    assert live_payout.transaction_id == "T_WAVE_99"

    live_session = WaveCheckoutSession.model_validate(
        {
            "id": "cos-err-1",
            "amount": "1500",
            "currency": "XOF",
            "checkout_status": "expired",
            "payment_status": "cancelled",
            "transaction_id": "T_CHK_1",
            "last_payment_error": {"code": "payer-cancelled", "message": "Cancelled"},
        }
    )
    assert live_session.transaction_id == "T_CHK_1"

    # 3. Live Wave-Signature (HMAC-SHA256(secret, timestamp + raw_body), NO dot)
    secret = "wave_sn_whsec_live"
    body = b'{"id":"ev_1","type":"checkout.session.completed"}'
    ts = str(int(time.time()))
    live_sig = hmac.new(secret.encode(), ts.encode() + body, hashlib.sha256).hexdigest()
    dot_sig = hmac.new(
        secret.encode(), f"{ts}.".encode() + body, hashlib.sha256
    ).hexdigest()

    # Default verify_timestamped_hmac_signature keeps "." separator
    WebhookHandler.verify_timestamped_hmac_signature(
        body, f"t={ts},v1={dot_sig}", secret
    )
    WebhookHandler.verify_timestamped_hmac_signature(
        body, f"t={ts},v1={live_sig}", secret, timestamp_separator=""
    )

    with WaveClient(WaveConfig(api_key="wk", webhook_secret=secret)) as wc_wh:
        wc_wh.verify_webhook(body, f"t={ts},v1={live_sig}")
        with pytest.raises(WebhookVerificationError):
            wc_wh.verify_webhook(body, f"t={ts},v1={dot_sig}")

    async with AsyncWaveClient(
        WaveConfig(api_key="wk", webhook_secret=secret)
    ) as awc_wh:
        awc_wh.verify_webhook(body, f"t={ts},v1={live_sig}")
        with pytest.raises(WebhookVerificationError):
            awc_wh.verify_webhook(body, f"t={ts},v1={dot_sig}")

    # 4. Sync payout sends receive_amount, strips 00 prefix, omits X-Reference-Id, retries via idempotent=True, and emits telemetry
    events: list[tuple[str, int | None]] = []

    class _Hook(TelemetryHook):
        def on_request(self, event: RequestTelemetryEvent) -> None:
            events.append((event.path, event.status_code))

        def on_webhook(self, event: WebhookTelemetryEvent) -> None:
            pass

    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/payout",
        status_code=503,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/payout",
        json={
            "id": "pt-live-1",
            "receive_amount": "5000",
            "currency": "XOF",
            "status": "failed",
            "client_reference": "ref-86",
            "transaction_id": "T_WAVE_86",
            "payout_error": {"code": "recipient-limit", "message": "Limit exceeded"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/checkout/sessions",
        json={
            "id": "cos-meta-1",
            "amount": "2000",
            "currency": "XOF",
            "checkout_status": "open",
            "payment_status": "processing",
            "transaction_id": "T_CHK_86",
            "last_payment_error": {"code": "err-1", "message": "Timed out"},
        },
        status_code=200,
    )

    # WaveProvider.collect does NOT fall back error_url to callback_url when config.error_url is unset
    with WaveClient(
        WaveConfig(
            api_key="wk",
            max_retries=1,
            retry_backoff=0.001,
            telemetry=_Hook(),
        )
    ) as wc:
        prov = WaveProvider(wc)
        with pytest.raises(ValueError, match="success_url and error_url"):
            prov.collect(
                PaymentRequest(
                    amount="2000",
                    currency="XOF",
                    payer_msisdn="221771234567",
                    callback_url="https://callback.example.test/success",
                )
            )

        # Configured error_url succeeds without touching private _config
        with WaveClient(
            WaveConfig(
                api_key="wk",
                error_url="https://callback.example.test/error",
            )
        ) as wc_err:
            col = WaveProvider(wc_err).collect(
                PaymentRequest(
                    amount="2000",
                    currency="XOF",
                    payer_msisdn="221771234567",
                    callback_url="https://callback.example.test/success",
                )
            )
            assert col.provider_transaction_id == "T_CHK_86"
            assert col.reason == "err-1: Timed out"

        payout = wc.create_payout(
            amount="5000",
            currency="XOF",
            mobile="00221771234567",
            client_reference="ref-86",
            name="Amina Diallo",
            payment_reason="Invoice 86",
            national_id="SN-12345",
            aggregated_merchant_id="agg-1",
        )
        assert payout.receive_amount == "5000"
        assert payout.transaction_id == "T_WAVE_86"

    reqs = httpx_mock.get_requests()
    payout_reqs = [r for r in reqs if r.url.path == "/v1/payout"]
    assert len(payout_reqs) == 2  # Retried safely with Idempotency-Key
    for req in payout_reqs:
        assert req.headers["Idempotency-Key"] == "ref-86"
        assert "X-Reference-Id" not in req.headers
        pbody = json.loads(req.read().decode("utf-8"))
        assert pbody["receive_amount"] == "5000"
        assert "amount" not in pbody
        assert pbody["mobile"] == "+221771234567"
        assert pbody["name"] == "Amina Diallo"
        assert pbody["payment_reason"] == "Invoice 86"
        assert pbody["national_id"] == "SN-12345"
        assert pbody["aggregated_merchant_id"] == "agg-1"
    assert ("/v1/payout", 200) in events

    # 5. Async parity: receive_amount, error_url required, and reason/provider_transaction_id populated
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/payout",
        json={
            "id": "pt-async-86",
            "receive_amount": "3000",
            "currency": "XOF",
            "status": "succeeded",
            "transaction_id": "T_ASYNC_86",
        },
        status_code=200,
    )
    async with AsyncWaveClient(WaveConfig(api_key="wk")) as awc:
        aprov = AsyncWaveProvider(awc)
        with pytest.raises(ValueError, match="success_url and error_url"):
            await aprov.collect(
                PaymentRequest(
                    amount="1000",
                    currency="XOF",
                    payer_msisdn="221771234567",
                    callback_url="https://callback.example.test/success",
                )
            )
        ad = await aprov.disburse(
            DisbursementRequest(
                amount="3000",
                currency="XOF",
                payee_msisdn="00221771234567",
                payer_message="Monthly bonus",
            )
        )
        assert ad.amount == "3000"
        assert ad.provider_transaction_id == "T_ASYNC_86"
        async_payout_req = [
            r for r in httpx_mock.get_requests() if r.url.path == "/v1/payout"
        ][-1]
        ap_body = json.loads(async_payout_req.read().decode("utf-8"))
        assert ap_body["receive_amount"] == "3000"
        assert ap_body["mobile"] == "+221771234567"
        assert ap_body["payment_reason"] == "Monthly bonus"
        assert "X-Reference-Id" not in async_payout_req.headers


@pytest.mark.asyncio
async def test_router_issue_88_thread_safety_reconciliation_lifecycle_and_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Issue #88: router lock, failover reference_id, capabilities, lifecycle closing, sync/async validation, models."""
    import concurrent.futures

    from pydantic import ValidationError

    import py_momo_sdk.providers.router as router_mod
    from py_momo_sdk import (
        BalanceResult,
        MpesaClient,
        MpesaConfig,
        MpesaProvider,
        OrangeMoneyClient,
        OrangeMoneyConfig,
        OrangeMoneyProvider,
        PaymentResult,
        ProviderCapabilities,
    )
    from py_momo_sdk.exceptions import PyMomoSDKServerError

    # 1. ProviderCapabilities normalizes currencies to uppercase; blank MSISDNs rejected
    caps = ProviderCapabilities(provider_id="custom", currencies=("ugx", " kes "))
    assert caps.currencies == ("UGX", "KES")
    with pytest.raises(ValidationError):
        PaymentRequest(amount="100", currency="UGX", payer_msisdn="   ")
    with pytest.raises(ValidationError):
        DisbursementRequest(amount="100", currency="UGX", payee_msisdn="")

    # 2. default_provider validated even when providers=()
    with pytest.raises(PyMomoSDKError, match="Default provider is not registered"):
        PaymentRouter(default_provider="missing")
    with pytest.raises(PyMomoSDKError, match="Default provider is not registered"):
        AsyncPaymentRouter(default_provider="missing")

    # 3. Sync/async provider type validation & lifecycle close
    closed_events: list[str] = []

    class _SyncStub:
        def __init__(self, name: str, *, fail_5xx: bool = False) -> None:
            self._name = name
            self._fail_5xx = fail_5xx
            self.seen_refs: list[str | None] = []
            self.seen_currency: str | None = None

        @property
        def name(self) -> str:
            return self._name

        @property
        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(
                provider_id=self._name,
                currencies=("UGX", "KES"),
            )

        def collect(self, request: PaymentRequest) -> PaymentResult:
            self.seen_refs.append(request.reference_id)
            if self._fail_5xx:
                raise PyMomoSDKServerError("upstream 503")
            return PaymentResult(
                provider=self._name,
                reference_id=request.reference_id or "gen",
                status=NormalizedStatus.PENDING,
            )

        def disburse(self, request: DisbursementRequest) -> PaymentResult:
            self.seen_refs.append(request.reference_id)
            if self._fail_5xx:
                raise PyMomoSDKServerError("upstream 503")
            return PaymentResult(
                provider=self._name,
                reference_id=request.reference_id or "gen",
                status=NormalizedStatus.PENDING,
            )

        def get_status(
            self, reference_id: str, *, kind: str = "collection"
        ) -> PaymentResult:
            return PaymentResult(
                provider=self._name,
                reference_id=reference_id,
                status=NormalizedStatus.SUCCEEDED,
            )

        def get_balance(
            self, *, kind: str = "collection", currency: str | None = None
        ) -> BalanceResult:
            self.seen_currency = currency
            return BalanceResult(
                provider=self._name,
                available_balance="100",
                currency=currency or "UGX",
            )

        def close(self) -> None:
            closed_events.append(f"sync:{self._name}")

    class _AsyncStub:
        def __init__(self, name: str, *, fail_5xx: bool = False) -> None:
            self._name = name
            self._fail_5xx = fail_5xx
            self.seen_refs: list[str | None] = []

        @property
        def name(self) -> str:
            return self._name

        @property
        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(
                provider_id=self._name,
                currencies=("UGX",),
            )

        async def collect(self, request: PaymentRequest) -> PaymentResult:
            self.seen_refs.append(request.reference_id)
            if self._fail_5xx:
                raise PyMomoSDKServerError("upstream 503")
            return PaymentResult(
                provider=self._name,
                reference_id=request.reference_id or "gen",
                status=NormalizedStatus.PENDING,
            )

        async def disburse(self, request: DisbursementRequest) -> PaymentResult:
            self.seen_refs.append(request.reference_id)
            return PaymentResult(
                provider=self._name,
                reference_id=request.reference_id or "gen",
                status=NormalizedStatus.PENDING,
            )

        async def get_status(
            self, reference_id: str, *, kind: str = "collection"
        ) -> PaymentResult:
            return PaymentResult(
                provider=self._name,
                reference_id=reference_id,
                status=NormalizedStatus.SUCCEEDED,
            )

        async def get_balance(
            self, *, kind: str = "collection", currency: str | None = None
        ) -> BalanceResult:
            return BalanceResult(
                provider=self._name,
                available_balance="200",
                currency=currency or "UGX",
            )

        async def aclose(self) -> None:
            closed_events.append(f"async:{self._name}")

    # Sync router rejects async provider; async router rejects sync provider
    with pytest.raises(TypeError, match="synchronous PaymentProvider"):
        PaymentRouter([_AsyncStub("a1")])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="asynchronous AsyncPaymentProvider"):
        AsyncPaymentRouter([_SyncStub("s1")])  # type: ignore[list-item]

    # 4. Pre-generated reconciliation reference_id on allow_ambiguous_write_fallback=True
    p1 = _SyncStub("rail1", fail_5xx=True)
    p2 = _SyncStub("rail2")
    with PaymentRouter([p1, p2]) as router:
        res = router.collect(
            PaymentRequest(amount="500", currency="UGX", payer_msisdn="256771234567"),
            fallback=True,
            allow_ambiguous_write_fallback=True,
        )
        assert p1.seen_refs[0] is not None
        assert p1.seen_refs[0] == p2.seen_refs[0] == res.reference_id
        assert res.raw["prior_failed_attempts"] == [
            {"provider": "rail1", "reference_id": p1.seen_refs[0]}
        ]
        # Currency forwarding on get_balance
        bal = router.get_balance(provider="rail2", currency="KES")
        assert bal.currency == "KES"
        assert p2.seen_currency == "KES"
    assert "sync:rail1" in closed_events and "sync:rail2" in closed_events

    ap1 = _AsyncStub("arail1", fail_5xx=True)
    ap2 = _AsyncStub("arail2")
    async with AsyncPaymentRouter([ap1, ap2]) as arouter:
        ares = await arouter.collect(
            PaymentRequest(amount="500", currency="UGX", payer_msisdn="256771234567"),
            fallback=True,
            allow_ambiguous_write_fallback=True,
        )
        assert ap1.seen_refs[0] is not None
        assert ap1.seen_refs[0] == ap2.seen_refs[0] == ares.reference_id
    assert "async:arail1" in closed_events and "async:arail2" in closed_events

    # 5. Capability checks on get_balance / get_status in PaymentRouter
    with (
        MpesaClient(
            MpesaConfig(
                consumer_key="ck",
                consumer_secret="cs",
                short_code="174379",
                passkey="pk",
            )
        ) as mp_client,
        OrangeMoneyClient(
            OrangeMoneyConfig(client_id="cid", client_secret="sec", merchant_key="mk")
        ) as om_client,
    ):
        cap_router = PaymentRouter(
            [MpesaProvider(mp_client), OrangeMoneyProvider(om_client)]
        )
        with pytest.raises(PyMomoSDKError, match="does not support balance"):
            cap_router.get_balance(provider="mpesa")
        with pytest.raises(PyMomoSDKError, match="does not support disbursement"):
            cap_router.get_status("ref-1", provider="orange_money", kind="disbursement")

    # 6. Thread safety under concurrent register() and _resolve_candidates()
    concurrent_router = PaymentRouter([_SyncStub("base")])

    def _worker(idx: int) -> list[str]:
        concurrent_router.register(_SyncStub(f"p-{idx % 10}"))
        cands = concurrent_router._resolve_candidates(
            provider=None,
            msisdn="256771234567",
            operation="collection",
            currency="UGX",
            fallback=True,
        )
        return [c.name for c in cands]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_worker, range(40)))
    assert all("base" in names for names in results)
    provs = concurrent_router.list_providers()
    assert len(provs) == len(set(provs))

    # 7. discover_provider_plugins: hybrid provider rejected; strict=False skips duplicate
    class _HybridStub(_SyncStub):
        async def collect(self, request: PaymentRequest) -> PaymentResult:  # type: ignore[override]
            return PaymentResult(
                provider=self._name,
                reference_id="r",
                status=NormalizedStatus.PENDING,
            )

    class _EP:
        def __init__(self, name: str, obj: object) -> None:
            self.name = name
            self._obj = obj

        def load(self) -> object:
            return self._obj

    monkeypatch.setattr(
        router_mod,
        "entry_points",
        lambda group: [_EP("hybrid", _HybridStub("h"))],
    )
    with pytest.raises(PyMomoSDKError, match="not a valid PaymentProvider"):
        discover_provider_plugins(strict=True)
    assert discover_provider_plugins(strict=False) == {}

    monkeypatch.setattr(
        router_mod,
        "entry_points",
        lambda group: [_EP("dup", _SyncStub("d1")), _EP("dup", _SyncStub("d2"))],
    )
    assert list(discover_provider_plugins(strict=False).keys()) == ["dup"]


@pytest.mark.asyncio
async def test_issue_159_cross_provider_router_reference_compatibility(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify Issue #159: router adapts cross-provider reference formats across Orange, MTN, and Paystack."""
    import json

    from py_momo_sdk import (
        AsyncFlutterwaveClient,
        AsyncFlutterwaveProvider,
        AsyncOrangeMoneyClient,
        AsyncOrangeMoneyProvider,
        AsyncPaystackClient,
        AsyncPaystackProvider,
        FlutterwaveConfig,
        OrangeMoneyClient,
        OrangeMoneyConfig,
        OrangeMoneyProvider,
        PaystackConfig,
    )
    from py_momo_sdk.utils import generate_reference_id, validate_reference_id

    om_cfg = OrangeMoneyConfig(
        client_id="om-cid",
        client_secret="om-sec",
        merchant_key="om-mk",
        return_url="https://merchant.example.test/ret",
        cancel_url="https://merchant.example.test/can",
        notif_url="https://merchant.example.test/notif",
    )

    # 1. Orange + Wave with allow_ambiguous_write_fallback=True (Orange 503 -> Wave succeeds)
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/oauth/v3/token",
        json={"access_token": "om-tok-159", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/dev/v1/webpayment",
        status_code=503,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/checkout/sessions",
        json={
            "id": "cos-159-wave",
            "amount": "5000",
            "currency": "XOF",
            "checkout_status": "open",
            "payment_status": "processing",
            "client_reference": "fallback-ok",
        },
        status_code=200,
    )

    with (
        OrangeMoneyClient(om_cfg) as omc,
        WaveClient(_wave_config()) as wc,
    ):
        router = PaymentRouter([OrangeMoneyProvider(omc), WaveProvider(wc)])
        res = router.collect(
            PaymentRequest(amount="5000", currency="XOF", payer_msisdn="221771234567"),
            fallback=True,
            allow_ambiguous_write_fallback=True,
        )
        assert res.provider == "wave"
        prior = res.raw["prior_failed_attempts"]
        assert len(prior) == 1
        assert prior[0]["provider"] == "orange_money"
        assert prior[0]["reference_id"] is not None
        assert len(prior[0]["reference_id"]) == 30
        assert prior[0]["reference_id"].startswith("om-")

        # Direct OrangeMoneyProvider with a 36-char UUID v4 also maps deterministically to <=30 chars
        httpx_mock.add_response(
            method="POST",
            url="https://api.orange.com/orange-money-webpay/dev/v1/webpayment",
            json={
                "pay_token": "om-direct-uuid",
                "payment_url": "https://webpay.orange.com/direct",
            },
            status_code=201,
        )
        uuid_ref = generate_reference_id()
        direct_om = OrangeMoneyProvider(omc).collect(
            PaymentRequest(
                amount="1000",
                currency="XOF",
                payer_msisdn="221771234567",
                reference_id=uuid_ref,
            )
        )
        assert direct_om.external_id is not None and len(direct_om.external_id) == 30

    # 2. Merchant reference "inv-2026-001" failing over from Airtel (401) to MTN MoMo (deterministic UUID v4)
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        status_code=401,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "mtn-159-tok",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay",
        status_code=202,
    )

    with (
        AirtelClient(_airtel_config()) as airtel_bad,
        PyMomoSDK(_mtn_config()) as mtn_ok,
    ):
        ug_router = PaymentRouter(
            [AirtelMoneyProvider(airtel_bad), MtnMomoProvider(mtn_ok)]
        )
        ug_res = ug_router.collect(
            PaymentRequest(
                amount="5000",
                currency="UGX",
                payer_msisdn="256751234567",
                reference_id="inv-2026-001",
            ),
            fallback=True,
        )
        assert ug_res.provider == "mtn_momo"
        validate_reference_id(ug_res.reference_id)
        assert ug_res.external_id == "inv-2026-001"

    # 3. Async disburse failover from Flutterwave (401) to Paystack with short/uppercase reference "INV-2026-001"
    httpx_mock.add_response(
        method="POST",
        url="https://api.flutterwave.com/v3/transfers",
        status_code=401,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transfer",
        json={"status": True, "data": {"status": "pending"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/oauth/v3/token",
        json={"access_token": "om-async-159", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/dev/v1/webpayment",
        json={
            "pay_token": "om-async-pt-159",
            "payment_url": "https://webpay.orange.com/async",
        },
        status_code=201,
    )

    async with (
        AsyncFlutterwaveClient(
            FlutterwaveConfig(secret_key="flw_bad", default_account_bank="MPS")
        ) as aflw,
        AsyncPaystackClient(PaystackConfig(secret_key="sk_ok")) as aps,
        AsyncOrangeMoneyClient(om_cfg) as aom,
        AsyncWaveClient(_wave_config()) as awave,
    ):
        disb_router = AsyncPaymentRouter(
            [AsyncFlutterwaveProvider(aflw), AsyncPaystackProvider(aps)]
        )
        disb_res = await disb_router.disburse(
            DisbursementRequest(
                amount="100.00",
                currency="NGN",
                payee_msisdn="0123456789",
                payee_bank_code="RCP_159",
                reference_id="INV-2026-001",
            ),
            fallback=True,
        )
        assert disb_res.provider == "paystack"
        assert disb_res.reference_id.startswith("ps-")
        assert len(disb_res.reference_id) == 32
        assert disb_res.external_id == "INV-2026-001"

        ps_req = next(r for r in httpx_mock.get_requests() if r.url.path == "/transfer")
        ps_body = json.loads(ps_req.read().decode("utf-8"))
        assert ps_body["reference"] == disb_res.reference_id

        # Async Orange + Wave with pre-generated UUID succeeds on Orange
        om_wave_router = AsyncPaymentRouter(
            [AsyncOrangeMoneyProvider(aom), AsyncWaveProvider(awave)]
        )
        aom_res = await om_wave_router.collect(
            PaymentRequest(amount="2500", currency="XOF", payer_msisdn="221771234567"),
            fallback=True,
            allow_ambiguous_write_fallback=True,
        )
        assert aom_res.provider == "orange_money"
        assert aom_res.external_id is not None and len(aom_res.external_id) == 30


@pytest.mark.asyncio
async def test_issue_160_wave_and_flutterwave_reference_reconciliation(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify Issue #160: WaveProvider and FlutterwaveProvider reconcile timed-out writes by merchant reference."""
    import httpx

    from py_momo_sdk import (
        AsyncFlutterwaveClient,
        AsyncFlutterwaveProvider,
        FlutterwaveClient,
        FlutterwaveConfig,
        FlutterwaveProvider,
        ResourceNotFoundError,
    )

    # 1. Wave timeout carries auto-generated client_reference, and get_status reconciles via search endpoints
    httpx_mock.add_exception(
        httpx.ReadTimeout("wave checkout timed out"),
        method="POST",
        url="https://api.wave.com/v1/checkout/sessions",
    )
    with WaveClient(_wave_config()) as wc:
        wprov = WaveProvider(wc)
        with pytest.raises(PyMomoSDKError) as exc_info:
            wprov.collect(
                PaymentRequest(
                    amount="1000", currency="XOF", payer_msisdn="221771234567"
                )
            )
        timed_out_ref = exc_info.value.reference_id
        assert timed_out_ref is not None and len(timed_out_ref) == 36

        httpx_mock.add_response(
            method="GET",
            url=f"https://api.wave.com/v1/checkout/sessions/search?client_reference={timed_out_ref}",
            json={
                "result": [
                    {
                        "id": "cos-reconciled-160",
                        "amount": "1000",
                        "currency": "XOF",
                        "checkout_status": "complete",
                        "payment_status": "succeeded",
                        "client_reference": timed_out_ref,
                        "transaction_id": "TWAVE160",
                    }
                ]
            },
            status_code=200,
        )
        reconciled = wprov.get_status(timed_out_ref, kind="collection")
        assert reconciled.is_successful()
        assert reconciled.reference_id == "cos-reconciled-160"
        assert reconciled.external_id == timed_out_ref

        httpx_mock.add_response(
            method="GET",
            url="https://api.wave.com/v1/payouts/search?client_reference=missing-payout-ref",
            json={"result": []},
            status_code=200,
        )
        with pytest.raises(ResourceNotFoundError):
            wprov.get_status("missing-payout-ref", kind="disbursement")

    # 2. Async Wave payout search reconciliation + Flutterwave sync & async transfer reference reconciliation
    flw_cfg = FlutterwaveConfig(
        secret_key="FLWSECK_TEST_160",
        default_account_bank="MPS",
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/transfers?reference=flw-merch-ref-160",
        json={
            "status": "success",
            "data": [
                {
                    "id": 990160,
                    "reference": "flw-merch-ref-160",
                    "status": "SUCCESSFUL",
                    "amount": 2500,
                    "currency": "UGX",
                    "complete_message": "Transfer Completed",
                }
            ],
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/transfers?reference=flw-missing-160",
        json={"status": "success", "data": []},
        status_code=200,
    )
    with FlutterwaveClient(flw_cfg) as fc:
        fprov = FlutterwaveProvider(fc)
        flw_st = fprov.get_status("flw-merch-ref-160", kind="disbursement")
        assert flw_st.is_successful()
        assert flw_st.provider_transaction_id == "990160"
        assert flw_st.external_id == "flw-merch-ref-160"
        assert flw_st.amount == "2500"

        with pytest.raises(ResourceNotFoundError):
            fprov.get_status("flw-missing-160", kind="disbursement")

    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/payouts/search?client_reference=wave-payout-ref-160",
        json={
            "result": [
                {
                    "id": "pt-160-async",
                    "receive_amount": "4000",
                    "currency": "XOF",
                    "status": "succeeded",
                    "client_reference": "wave-payout-ref-160",
                }
            ]
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/transfers?reference=flw-async-ref-160",
        json={
            "status": "success",
            "data": [
                {
                    "id": 990161,
                    "reference": "flw-async-ref-160",
                    "status": "PENDING",
                    "amount": 1500,
                    "currency": "KES",
                }
            ],
        },
        status_code=200,
    )
    async with (
        AsyncWaveClient(_wave_config()) as awc,
        AsyncFlutterwaveClient(flw_cfg) as afc,
    ):
        awprov = AsyncWaveProvider(awc)
        afprov = AsyncFlutterwaveProvider(afc)

        aw_st = await awprov.get_status("wave-payout-ref-160", kind="disbursement")
        assert aw_st.is_successful()
        assert aw_st.reference_id == "pt-160-async"

        af_st = await afprov.get_status("flw-async-ref-160", kind="disbursement")
        assert af_st.is_pending()
        assert af_st.provider_transaction_id == "990161"


@pytest.mark.asyncio
async def test_issue_161_wave_signature_all_endpoints_and_retry_refresh(
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Issue #161: Wave-Signature is sent and verified on all Wave endpoints and refreshed across retries."""
    import py_momo_sdk.providers.wave as wave_mod
    from py_momo_sdk import WebhookHandler

    signing_secret = "wave_sn_AKS_issue161"

    def _assert_valid_wave_sig(req_headers: dict[str, str], raw_body: bytes) -> int:
        sig_header = req_headers.get("wave-signature") or req_headers.get(
            "Wave-Signature"
        )
        assert sig_header is not None
        ts_part = sig_header.split(",")[0].split("=")[1]
        ts = int(ts_part)
        WebhookHandler.verify_timestamped_hmac_signature(
            raw_body,
            sig_header,
            signing_secret,
            timestamp_separator="",
            now=float(ts),
        )
        return ts

    # Sync: test all 10 Wave endpoints + retry timestamp refresh
    orig_sign = wave_mod._sign_wave_request
    timestamps = iter(
        [
            1700000100,
            1700000145,
            1700000200,
            1700000201,
            1700000202,
            1700000203,
            1700000204,
            1700000205,
            1700000206,
            1700000207,
            1700000208,
        ]
    )
    monkeypatch.setattr(
        wave_mod,
        "_sign_wave_request",
        lambda body, secret, timestamp=None: orig_sign(
            body, secret, timestamp=next(timestamps)
        ),
    )

    # First checkout call gets 503 then 200 to verify fresh signature timestamp on retry
    httpx_mock.add_response(
        method="POST", url="https://api.wave.com/v1/checkout/sessions", status_code=503
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/checkout/sessions",
        json={"id": "cos-161", "amount": "1000", "currency": "XOF"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/checkout/sessions/cos-161",
        json={"id": "cos-161", "amount": "1000", "currency": "XOF"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/checkout/sessions/cos-161/refund",
        json={"status": "refunded"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/checkout/sessions/cos-161/expire",
        json={"status": "expired"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/checkout/sessions/search?client_reference=cref-161",
        json={"result": []},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/payout",
        json={
            "id": "pt-161",
            "receive_amount": "500",
            "currency": "XOF",
            "status": "succeeded",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/payout/pt-161",
        json={
            "id": "pt-161",
            "receive_amount": "500",
            "currency": "XOF",
            "status": "succeeded",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/payout/pt-161/reverse",
        json={"status": "reversed"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/payouts/search?client_reference=pref-161",
        json={"result": []},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/balance",
        json={"amount": "9000", "currency": "XOF"},
        status_code=200,
    )

    cfg = WaveConfig(
        api_key="wave_sn_test_161",
        signing_secret=signing_secret,
        success_url="https://merchant.example.test/ok",
        error_url="https://merchant.example.test/err",
        max_retries=1,
        retry_backoff=0.001,
    )
    with WaveClient(cfg) as wc:
        wc.create_checkout_session("1000", "XOF", client_reference="cref-161")
        wc.get_checkout_session("cos-161")
        wc.refund_checkout_session("cos-161")
        wc.expire_checkout_session("cos-161")
        wc.search_checkout_sessions("cref-161")
        wc.create_payout("500", "XOF", "221771234567", client_reference="pref-161")
        wc.get_payout("pt-161")
        wc.reverse_payout("pt-161")
        wc.search_payouts("pref-161")
        wc.get_balance()

    sync_reqs = httpx_mock.get_requests()
    assert len(sync_reqs) == 11
    seen_ts = [_assert_valid_wave_sig(dict(r.headers), r.read()) for r in sync_reqs]
    # Retry attempt #2 got a refreshed Wave-Signature timestamp (1700000145 > 1700000100)
    assert seen_ts[0] == 1700000100
    assert seen_ts[1] == 1700000145

    # Async parity across checkout, search, balance, and retry
    async_timestamps = iter([1700000500, 1700000535, 1700000600, 1700000601])
    monkeypatch.setattr(
        wave_mod,
        "_sign_wave_request",
        lambda body, secret, timestamp=None: orig_sign(
            body, secret, timestamp=next(async_timestamps)
        ),
    )

    httpx_mock.add_response(
        method="GET", url="https://api.wave.com/v1/balance", status_code=503
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/balance",
        json={"amount": "12000", "currency": "XOF"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/checkout/sessions",
        json={"id": "cos-a161", "amount": "2000", "currency": "XOF"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.wave.com/v1/checkout/sessions/cos-a161",
        json={"id": "cos-a161", "amount": "2000", "currency": "XOF"},
        status_code=200,
    )
    async with AsyncWaveClient(cfg) as awc:
        await awc.get_balance()
        await awc.create_checkout_session("2000", "XOF", client_reference="acref-161")
        await awc.get_checkout_session("cos-a161")

    async_reqs = httpx_mock.get_requests()[11:]
    assert len(async_reqs) == 4
    async_ts = [_assert_valid_wave_sig(dict(r.headers), r.read()) for r in async_reqs]
    assert async_ts[0] == 1700000500
    assert async_ts[1] == 1700000535
