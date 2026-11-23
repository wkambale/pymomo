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
            ]
        )
        # Senegal Wave MSISDN routes automatically to Wave
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
        url="https://openapiuat.airtel.africa/merchant/v2/wallets/balance/",
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
        url="https://openapiuat.airtel.africa/merchant/v2/wallets/balance/",
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
            )
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
