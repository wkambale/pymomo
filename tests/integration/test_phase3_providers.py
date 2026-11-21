from __future__ import annotations

import hashlib
import hmac

import pytest
from pytest_httpx import HTTPXMock

from py_momo_sdk import (
    AsyncFlutterwaveClient,
    AsyncFlutterwaveProvider,
    AsyncMpesaClient,
    AsyncMpesaProvider,
    AsyncOrangeMoneyClient,
    AsyncOrangeMoneyProvider,
    AsyncPaymentRouter,
    AsyncPaystackClient,
    AsyncPaystackProvider,
    DisbursementRequest,
    FlutterwaveClient,
    FlutterwaveConfig,
    FlutterwaveProvider,
    MpesaClient,
    MpesaConfig,
    MpesaProvider,
    OrangeMoneyClient,
    OrangeMoneyConfig,
    OrangeMoneyProvider,
    PaymentRequest,
    PaymentRouter,
    PaystackClient,
    PaystackConfig,
    PaystackProvider,
)


def test_mpesa_client_and_provider_sync(httpx_mock: HTTPXMock) -> None:
    """Test MpesaClient and MpesaProvider STK Push, query, and B2C."""
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials",
        json={"access_token": "mpesa-tok", "expires_in": "3599"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
        json={
            "MerchantRequestID": "mr-1",
            "CheckoutRequestID": "ws_CO_123",
            "ResponseCode": "0",
            "ResponseDescription": "Success. Request accepted",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
        json={
            "CheckoutRequestID": "ws_CO_123",
            "ResultCode": "0",
            "ResultDesc": "The service request is processed successfully.",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/b2c/v3/paymentrequest",
        json={
            "ConversationID": "AG_2026_1",
            "OriginatorConversationID": "oc-1",
            "ResponseCode": "0",
            "ResponseDescription": "Accept the service request successfully.",
        },
        status_code=200,
    )

    cfg = MpesaConfig(
        consumer_key="ck",
        consumer_secret="cs",
        short_code="174379",
        passkey="pass",
        callback_url="https://callback.example.test/mpesa",
        security_credential="sec-cred",
    )
    assert "cs" not in repr(cfg)

    with MpesaClient(cfg) as client:
        router = PaymentRouter([MpesaProvider(client)])
        col = router.collect(
            PaymentRequest(
                amount="100",
                currency="KES",
                payer_msisdn="254712345678",
                external_id="inv-ke-1",
            )
        )
        assert col.provider == "mpesa"
        assert col.reference_id == "ws_CO_123"
        assert col.is_pending()

        st = router.get_status("ws_CO_123", provider="mpesa")
        assert st.is_successful()

        disb = router.disburse(
            DisbursementRequest(
                amount="500",
                currency="KES",
                payee_msisdn="254712345678",
                external_id="b2c-1",
            )
        )
        assert disb.reference_id == "AG_2026_1"


def test_paystack_flutterwave_orange_sync(httpx_mock: HTTPXMock) -> None:
    """Test Paystack, Flutterwave, and Orange Money sync clients and providers."""
    # Paystack
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transaction/initialize",
        json={
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/abc",
                "reference": "ps-ref-1",
            },
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.paystack.co/transaction/verify/ps-ref-1",
        json={"status": True, "data": {"status": "success", "currency": "NGN"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transfer",
        json={"status": True, "data": {"reference": "ps-tr-1", "status": "success"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.paystack.co/balance",
        json={"status": True, "data": [{"balance": 250000, "currency": "NGN"}]},
        status_code=200,
    )

    ps_cfg = PaystackConfig(secret_key="sk_test_secret")
    assert "sk_test_secret" not in repr(ps_cfg)
    with PaystackClient(ps_cfg) as ps_client:
        ps = PaystackProvider(ps_client)
        col = ps.collect(
            PaymentRequest(amount="50.00", currency="NGN", payer_msisdn="2348012345678")
        )
        assert col.checkout_url == "https://checkout.paystack.com/abc"
        assert ps.get_status("ps-ref-1").is_successful()
        assert ps.disburse(
            DisbursementRequest(amount="25.00", currency="NGN", payee_msisdn="RCP_123")
        ).is_successful()
        assert ps.get_balance().available_balance == "2500.00"

        raw = b'{"event":"charge.success"}'
        sig = hmac.new(b"sk_test_secret", raw, hashlib.sha512).hexdigest()
        ps_client.verify_webhook(raw, sig)

    # Flutterwave
    httpx_mock.add_response(
        method="POST",
        url="https://api.flutterwave.com/v3/payments",
        json={
            "status": "success",
            "data": {"link": "https://checkout.flutterwave.com/1"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/transactions/verify_by_reference?tx_ref=flw-1",
        json={"status": "success", "data": {"status": "successful", "currency": "UGX"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/balances/NGN",
        json={
            "status": "success",
            "data": {"available_balance": 1500.5, "currency": "NGN"},
        },
        status_code=200,
    )
    flw_cfg = FlutterwaveConfig(
        secret_key="FLWSECK_TEST",
        webhook_hash="flw-hash",
        redirect_url="https://callback.example.test/flutterwave",
    )
    assert "FLWSECK_TEST" not in repr(flw_cfg)
    with FlutterwaveClient(flw_cfg) as flw_client:
        flw = FlutterwaveProvider(flw_client)
        res = flw.collect(
            PaymentRequest(
                amount="1000",
                currency="UGX",
                payer_msisdn="256771234567",
                reference_id="flw-1",
            )
        )
        assert res.checkout_url == "https://checkout.flutterwave.com/1"
        assert flw.get_status("flw-1").is_successful()
        assert flw.get_balance().available_balance == "1500.5"
        flw_client.verify_webhook_hash("flw-hash")

    # Orange Money
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/oauth/v3/token",
        json={"access_token": "om-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/dev/v1/webpayment",
        json={"pay_token": "om-pay-1", "payment_url": "https://webpay.orange.com/1"},
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/dev/v1/transactionstatus",
        json={"status": "SUCCESS"},
        status_code=200,
    )
    om_cfg = OrangeMoneyConfig(
        client_id="om-id",
        client_secret="om-sec",
        merchant_key="om-mk",
        return_url="https://callback.example.test/orange/return",
        cancel_url="https://callback.example.test/orange/cancel",
        notif_url="https://callback.example.test/orange/webhook",
    )
    assert "om-sec" not in repr(om_cfg)
    with OrangeMoneyClient(om_cfg) as om_client:
        om = OrangeMoneyProvider(om_client)
        col = om.collect(
            PaymentRequest(amount="500", currency="XOF", payer_msisdn="221771234567")
        )
        assert col.reference_id == "om-pay-1"
        assert col.checkout_url == "https://webpay.orange.com/1"
        assert om.get_status("om-pay-1").is_successful()


@pytest.mark.asyncio
async def test_phase3_async_providers_and_router(httpx_mock: HTTPXMock) -> None:
    """Test async M-Pesa, Paystack, Flutterwave, and Orange Money providers."""
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials",
        json={"access_token": "mpesa-async-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
        json={"CheckoutRequestID": "ws_async_1", "ResponseCode": "0"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.paystack.co/balance",
        json={"status": True, "data": [{"balance": 5000, "currency": "NGN"}]},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/balances/NGN",
        json={
            "status": "success",
            "data": {"available_balance": 900, "currency": "NGN"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/oauth/v3/token",
        json={"access_token": "om-async-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/dev/v1/webpayment",
        json={
            "pay_token": "om-async-pay",
            "payment_url": "https://webpay.orange.com/a",
        },
        status_code=201,
    )

    async with (
        AsyncMpesaClient(
            MpesaConfig(
                consumer_key="ck",
                consumer_secret="cs",
                short_code="174379",
                passkey="pass",
                callback_url="https://callback.example.test/mpesa",
            )
        ) as mpesa,
        AsyncPaystackClient(PaystackConfig(secret_key="sk_test")) as paystack,
        AsyncFlutterwaveClient(FlutterwaveConfig(secret_key="FLWSECK")) as flw,
        AsyncOrangeMoneyClient(
            OrangeMoneyConfig(
                client_id="om-id",
                client_secret="om-sec",
                merchant_key="om-mk",
                return_url="https://callback.example.test/orange/return",
                cancel_url="https://callback.example.test/orange/cancel",
                notif_url="https://callback.example.test/orange/webhook",
            )
        ) as orange,
    ):
        router = AsyncPaymentRouter(
            [
                AsyncMpesaProvider(mpesa),
                AsyncPaystackProvider(paystack),
                AsyncFlutterwaveProvider(flw),
                AsyncOrangeMoneyProvider(orange),
            ]
        )
        # 25471... routes to mpesa; 22177... routes to orange_money
        ke_res = await router.collect(
            PaymentRequest(amount="100", currency="KES", payer_msisdn="254712345678")
        )
        assert ke_res.provider == "mpesa"
        assert ke_res.reference_id == "ws_async_1"

        sn_res = await router.collect(
            PaymentRequest(amount="500", currency="XOF", payer_msisdn="221771234567")
        )
        assert sn_res.provider == "orange_money"
        assert sn_res.reference_id == "om-async-pay"

        assert (
            await router.get_balance(provider="paystack")
        ).available_balance == "50.00"
        assert (
            await router.get_balance(provider="flutterwave")
        ).available_balance == "900"


def test_provider_config_and_input_validation_hardening() -> None:
    """Test HTTPS callback, base_url, environment, retry, and write-input checks."""
    from pydantic import ValidationError

    from py_momo_sdk import AirtelConfig, PyMomoSDKError, WaveClient, WaveConfig

    # 1. Unified request models reject plaintext/malformed callback URLs
    with pytest.raises(ValidationError):
        PaymentRequest(
            amount="10",
            currency="UGX",
            payer_msisdn="256771234567",
            callback_url="http://insecure.example.test/webhook",
        )
    with pytest.raises(ValidationError):
        DisbursementRequest(
            amount="10",
            currency="UGX",
            payee_msisdn="256771234567",
            callback_url="javascript:alert(1)",
        )

    # 2. Environment allowlisting blocks silent production fallback
    with pytest.raises(ValueError, match="sandbox"):
        AirtelConfig(
            client_id="id",
            client_secret="sec",
            country="UG",
            currency="UGX",
            environment="SANDBOX",
        )
    with pytest.raises(ValueError, match="sandbox"):
        MpesaConfig(
            consumer_key="ck",
            consumer_secret="cs",
            short_code="174379",
            passkey="pk",
            environment="uat",
        )

    # 3. Provider configs validate base_url, max_retries, retry_backoff, and headers
    with pytest.raises(PyMomoSDKError, match="HTTPS"):
        PaystackConfig(secret_key="sk", base_url="http://insecure.local")
    with pytest.raises(PyMomoSDKError, match="HTTPS"):
        WaveConfig(api_key="wk", base_url="http://insecure.local")
    with pytest.raises(PyMomoSDKError, match="HTTPS"):
        FlutterwaveConfig(secret_key="fk", base_url="http://insecure.local")
    with pytest.raises(PyMomoSDKError, match="HTTPS"):
        OrangeMoneyConfig(
            client_id="id",
            client_secret="sec",
            merchant_key="mk",
            base_url="http://insecure.local",
        )
    with pytest.raises(PyMomoSDKError, match="HTTPS"):
        AirtelConfig(
            client_id="id",
            client_secret="sec",
            country="UG",
            currency="UGX",
            base_url="http://insecure.local",
        )
    with pytest.raises(ValueError, match="max_retries"):
        PaystackConfig(secret_key="sk", max_retries=-1)
    with pytest.raises(ValueError, match="max_retries"):
        WaveConfig(api_key="wk", max_retries=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="retry_backoff"):
        FlutterwaveConfig(secret_key="fk", retry_backoff=float("inf"))
    with pytest.raises(ValueError, match="initiator_name"):
        MpesaConfig(
            consumer_key="ck",
            consumer_secret="cs",
            short_code="174379",
            passkey="pk",
            initiator_name="bad\r\nheader",
        )

    # 4. Production MpesaConfig does not default initiator_name to "testapi"
    prod_mpesa = MpesaConfig(
        consumer_key="ck",
        consumer_secret="cs",
        short_code="174379",
        passkey="pk",
        environment="production",
        security_credential="cred",
        callback_url="https://callback.example.test/mpesa",
    )
    assert prod_mpesa.initiator_name is None
    with MpesaClient(prod_mpesa) as mp_client:
        with pytest.raises(ValueError, match="initiator_name"):
            mp_client.b2c_transfer(amount="100", phone_number="254712345678")
        with pytest.raises(ValueError, match="HTTPS"):
            mp_client.stk_push(
                amount="100",
                phone_number="254712345678",
                account_reference="ref",
                callback_url="http://insecure.example.test/cb",
            )

    # 5. Direct provider write methods validate amount, currency, callback URLs, and headers
    with WaveClient(WaveConfig(api_key="wk")) as wave_client:
        with pytest.raises(ValueError, match="success_url and error_url"):
            wave_client.create_checkout_session(amount="100", currency="XOF")
        with pytest.raises(ValueError, match="HTTPS"):
            wave_client.create_checkout_session(
                amount="100",
                currency="XOF",
                success_url="http://insecure.example.test/ok",
                error_url="https://callback.example.test/err",
            )
        with pytest.raises(ValueError, match="positive decimal"):
            wave_client.create_payout(
                amount="-10", currency="XOF", mobile="221771234567"
            )
        with pytest.raises(ValueError, match="(?i)currency"):
            wave_client.create_payout(
                amount="10", currency="BAD!", mobile="221771234567"
            )
        with pytest.raises(ValueError, match="client_reference"):
            wave_client.create_payout(
                amount="10",
                currency="XOF",
                mobile="221771234567",
                client_reference="ref\r\ninject",
            )
    with (
        PaystackClient(PaystackConfig(secret_key="sk")) as ps_client,
        pytest.raises(ValueError, match="HTTPS"),
    ):
        ps_client.initialize_transaction(
            email="a@b.com",
            amount="10.00",
            currency="NGN",
            callback_url="http://insecure.example.test/cb",
        )
    with (
        FlutterwaveClient(FlutterwaveConfig(secret_key="fk")) as flw_client,
        pytest.raises(ValueError, match="HTTPS"),
    ):
        flw_client.create_payment(
            amount="10",
            currency="NGN",
            phone_number="2348012345678",
            tx_ref="tx-1",
            redirect_url="http://insecure.example.test/cb",
        )
    with (
        OrangeMoneyClient(
            OrangeMoneyConfig(client_id="id", client_secret="sec", merchant_key="mk")
        ) as om_client,
        pytest.raises(ValueError, match="return_url, cancel_url, and notif_url"),
    ):
        om_client.create_web_payment(
            amount="100",
            currency="XOF",
            order_id="ord-1",
        )


@pytest.mark.asyncio
async def test_async_provider_input_validation_hardening() -> None:
    """Test async provider client write-input and callback URL validation."""
    from py_momo_sdk import AsyncWaveClient, WaveConfig

    async with AsyncWaveClient(WaveConfig(api_key="wk")) as wave_client:
        with pytest.raises(ValueError, match="success_url and error_url"):
            await wave_client.create_checkout_session(amount="100", currency="XOF")
        with pytest.raises(ValueError, match="HTTPS"):
            await wave_client.create_checkout_session(
                amount="100",
                currency="XOF",
                success_url="http://insecure.example.test/ok",
                error_url="https://callback.example.test/err",
            )
    async with AsyncPaystackClient(PaystackConfig(secret_key="sk")) as ps_client:
        with pytest.raises(ValueError, match="HTTPS"):
            await ps_client.initialize_transaction(
                email="a@b.com",
                amount="10.00",
                currency="NGN",
                callback_url="http://insecure.example.test/cb",
            )
        with pytest.raises(ValueError, match="positive decimal"):
            await ps_client.initiate_transfer(
                amount="-5", currency="NGN", recipient="RCP_1"
            )
    async with AsyncFlutterwaveClient(FlutterwaveConfig(secret_key="fk")) as flw_client:
        with pytest.raises(ValueError, match="HTTPS"):
            await flw_client.create_payment(
                amount="10",
                currency="NGN",
                phone_number="2348012345678",
                redirect_url="http://insecure.example.test/cb",
            )
        with pytest.raises(ValueError, match="greater than zero"):
            await flw_client.create_transfer(
                amount="0", currency="NGN", account_number="2348012345678"
            )
    async with AsyncOrangeMoneyClient(
        OrangeMoneyConfig(client_id="id", client_secret="sec", merchant_key="mk")
    ) as om_client:
        with pytest.raises(ValueError, match="return_url, cancel_url, and notif_url"):
            await om_client.create_web_payment(amount="100", currency="XOF")
    prod_mpesa = MpesaConfig(
        consumer_key="ck",
        consumer_secret="cs",
        short_code="174379",
        passkey="pk",
        environment="production",
        security_credential="cred",
        callback_url="https://callback.example.test/mpesa",
    )
    async with AsyncMpesaClient(prod_mpesa) as mp_client:
        with pytest.raises(ValueError, match="initiator_name"):
            await mp_client.b2c_transfer(amount="100", phone_number="254712345678")
        with pytest.raises(ValueError, match="HTTPS"):
            await mp_client.stk_push(
                amount="100",
                phone_number="254712345678",
                account_reference="ref",
                callback_url="http://insecure.example.test/cb",
            )
