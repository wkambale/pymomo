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

    ps_cfg = PaystackConfig(
        secret_key="sk_test_secret",
        default_customer_email="customer@example.test",
    )
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
        default_customer_email="customer@example.test",
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
            email="a@b.com",
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
                email="a@b.com",
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


def test_provider_contracts_currency_schemas_and_status_mappings(
    httpx_mock: HTTPXMock,
) -> None:
    """Test #59 fixes: Airtel currency/PIN, Paystack/FLW/Orange contracts, kind, and statuses."""
    import base64
    import json

    from py_momo_sdk import (
        AirtelClient,
        AirtelConfig,
        AirtelMoneyProvider,
        NormalizedStatus,
        PyMomoSDKError,
        WaveClient,
        WaveConfig,
        WaveProvider,
        encrypt_airtel_pin,
    )
    from py_momo_sdk.airtel.models import AirtelTransactionResponse
    from py_momo_sdk.providers.airtel import _map_airtel_result
    from py_momo_sdk.providers.mpesa import MpesaStkQueryResponse, _map_mpesa_query
    from py_momo_sdk.providers.orange import _map_orange_status
    from py_momo_sdk.providers.wave import WaveCheckoutSession, _map_wave_session_status

    # 1. Airtel production PIN guard and currency match enforcement
    with pytest.raises(ValueError, match="RSA-encrypted Base64 PIN"):
        AirtelConfig(
            client_id="id",
            client_secret="sec",
            country="UG",
            currency="UGX",
            environment="production",
            pin="1234",
        )
    valid_rsa_b64 = base64.b64encode(b"x" * 128).decode("ascii")
    prod_airtel = AirtelConfig(
        client_id="id",
        client_secret="sec",
        country="UG",
        currency="UGX",
        environment="production",
        pin=valid_rsa_b64,
    )
    assert prod_airtel.base_url == "https://openapi.airtel.africa"
    with pytest.raises(ValueError, match="non-empty"):
        encrypt_airtel_pin("", "-----BEGIN PUBLIC KEY-----")

    with AirtelClient(
        AirtelConfig(
            client_id="id",
            client_secret="sec",
            country="UG",
            currency="UGX",
            pin="1234",
        )
    ) as airtel_client:
        ap = AirtelMoneyProvider(airtel_client)
        with pytest.raises(
            ValueError, match="does not match configured Airtel currency"
        ):
            ap.collect(
                PaymentRequest(
                    amount="100", currency="KES", payer_msisdn="254731234567"
                )
            )
        with pytest.raises(
            ValueError, match="does not match configured Airtel currency"
        ):
            ap.disburse(
                DisbursementRequest(
                    amount="100", currency="KES", payee_msisdn="254731234567"
                )
            )
        with pytest.raises(ValueError, match="kind must be"):
            ap.get_status("e4d6934c-6fa1-49b4-9c59-bf558661b17c", kind="refund")

    # Indeterminate Airtel 00 response maps to PENDING, not FAILED
    indeterminate = AirtelTransactionResponse.model_validate(
        {
            "status": {"code": "200", "message": "Accepted", "result_code": "00"},
            "data": {"transaction": {"id": "tx-ind"}},
        }
    )
    assert (
        _map_airtel_result("tx-ind", indeterminate).status == NormalizedStatus.PENDING
    )

    # 2. Status mapping edge cases (Wave, Orange, M-Pesa)
    assert (
        _map_wave_session_status(
            WaveCheckoutSession(
                id="cos-1",
                amount="100",
                currency="XOF",
                checkout_status="expired",
                payment_status="processing",
            )
        )
        == NormalizedStatus.EXPIRED
    )
    assert (
        _map_wave_session_status(
            WaveCheckoutSession(
                id="cos-2",
                amount="100",
                currency="XOF",
                checkout_status="complete",
                payment_status="reversed",
            )
        )
        == NormalizedStatus.REVERSED
    )
    assert _map_orange_status("EXPIRED") == NormalizedStatus.EXPIRED
    assert _map_orange_status("CANCELLED") == NormalizedStatus.FAILED
    assert (
        _map_mpesa_query(
            "ws_1", MpesaStkQueryResponse(CheckoutRequestID="ws_1", ResultCode=None)
        ).status
        == NormalizedStatus.PENDING
    )

    # 3. Paystack minor-unit truncation, null data, recipient guard, and transfer verify
    httpx_mock.add_response(
        method="GET",
        url="https://api.paystack.co/transfer/verify/ps-tr-1",
        json={
            "status": True,
            "data": {
                "id": 991,
                "status": "success",
                "amount": 2550,
                "currency": "NGN",
                "reason": "Settled",
            },
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.paystack.co/transaction/verify/ps-null",
        json={"status": False, "message": "Verification failed", "data": None},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.paystack.co/balance",
        json={"status": True, "data": []},
        status_code=200,
    )
    with PaystackClient(PaystackConfig(secret_key="sk_test")) as ps_client:
        ps = PaystackProvider(ps_client)
        with pytest.raises(ValueError, match="payer_email"):
            ps.collect(
                PaymentRequest(
                    amount="10.00", currency="NGN", payer_msisdn="2348012345678"
                )
            )
        with pytest.raises(ValueError, match="more than 2 decimal places"):
            ps_client.initialize_transaction(
                email="a@b.com", amount="10.999", currency="NGN"
            )
        with pytest.raises(ValueError, match="RCP_"):
            ps.disburse(
                DisbursementRequest(
                    amount="10.00", currency="NGN", payee_msisdn="2348012345678"
                )
            )
        tr_status = ps.get_status("ps-tr-1", kind="disbursement")
        assert tr_status.is_successful()
        assert tr_status.amount == "25.50"
        assert tr_status.provider_transaction_id == "991"
        with pytest.raises(PyMomoSDKError, match="Verification failed"):
            ps.get_status("ps-null")
        with pytest.raises(PyMomoSDKError, match="Malformed Paystack balance"):
            ps.get_balance()

    # 4. Flutterwave explicit email/account_bank, transfer verify, and malformed balance
    httpx_mock.add_response(
        method="POST",
        url="https://api.flutterwave.com/v3/transfers",
        json={
            "status": "success",
            "data": {"id": 7788, "reference": "flw-tr-1", "status": "NEW"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/transfers/7788",
        json={
            "status": "success",
            "data": {
                "id": 7788,
                "status": "SUCCESSFUL",
                "amount": 500,
                "currency": "KES",
            },
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/balances/NGN",
        json={"status": "success", "data": {}},
        status_code=200,
    )
    with FlutterwaveClient(FlutterwaveConfig(secret_key="FLWSECK")) as flw_client:
        flw = FlutterwaveProvider(flw_client)
        with pytest.raises(ValueError, match="email"):
            flw.collect(
                PaymentRequest(
                    amount="100", currency="KES", payer_msisdn="254712345678"
                )
            )
        with pytest.raises(ValueError, match="account_bank"):
            flw.disburse(
                DisbursementRequest(
                    amount="100", currency="KES", payee_msisdn="254712345678"
                )
            )
        disb_res = flw.disburse(
            DisbursementRequest(
                amount="500",
                currency="KES",
                payee_msisdn="254712345678",
                payee_bank_code="MPS",
                reference_id="flw-tr-1",
            )
        )
        assert disb_res.reference_id == "7788"
        assert disb_res.external_id == "flw-tr-1"
        assert flw.get_status("7788", kind="disbursement").is_successful()
        with pytest.raises(PyMomoSDKError, match="Malformed Flutterwave balance"):
            flw.get_balance()

    # 5. Orange Money country path prefix, real status context, and disbursement guard
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/oauth/v3/token",
        json={"access_token": "om-sn-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/sn/v1/webpayment",
        json={"pay_token": "om-sn-pay", "payment_url": "https://webpay.orange.sn/1"},
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/sn/v1/transactionstatus",
        json={"status": "EXPIRED"},
        status_code=200,
    )
    with OrangeMoneyClient(
        OrangeMoneyConfig(
            client_id="id",
            client_secret="sec",
            merchant_key="mk",
            api_path_prefix="/orange-money-webpay/sn/v1/",
            notif_url="https://callback.example.test/orange",
        )
    ) as om_client:
        om = OrangeMoneyProvider(om_client)
        with pytest.raises(PyMomoSDKError, match="order_id and amount"):
            om.get_status("unknown-pay-token")
        with pytest.raises(NotImplementedError):
            om.get_status("om-sn-pay", kind="disbursement")
        om.collect(
            PaymentRequest(
                amount="750",
                currency="XOF",
                payer_msisdn="221771234567",
                reference_id="ord-sn-1",
            )
        )
        st = om.get_status("om-sn-pay")
        assert st.status == NormalizedStatus.EXPIRED
        status_req = next(
            r
            for r in httpx_mock.get_requests()
            if r.url.path.endswith("/transactionstatus")
        )
        sent_status = json.loads(status_req.read().decode("utf-8"))
        assert sent_status == {
            "order_id": "ord-sn-1",
            "amount": "750",
            "pay_token": "om-sn-pay",
        }

    # 6. M-Pesa and Wave kind validation
    with MpesaClient(
        MpesaConfig(
            consumer_key="ck",
            consumer_secret="cs",
            short_code="174379",
            passkey="pk",
        )
    ) as mp_client:
        mp = MpesaProvider(mp_client)
        with pytest.raises(NotImplementedError, match="ResultURL"):
            mp.get_status("AG_1", kind="disbursement")
        with pytest.raises(ValueError, match="kind must be"):
            mp.get_status("ws_1", kind="other")
    with WaveClient(WaveConfig(api_key="wk")) as wave_client:
        wp = WaveProvider(wave_client)
        with pytest.raises(ValueError, match="kind must be"):
            wp.get_status("cos-1", kind="other")


@pytest.mark.asyncio
async def test_async_provider_contracts_and_pin_encryption(
    httpx_mock: HTTPXMock,
) -> None:
    """Test async provider contracts (#59) and encrypt_airtel_pin paths."""
    import base64
    import types
    from unittest.mock import patch

    from py_momo_sdk import AirtelConfig, encrypt_airtel_pin

    # 1. Invalid/short Base64 PIN guards & encrypt_airtel_pin unit branches
    with pytest.raises(ValueError, match="Base64"):
        AirtelConfig(
            client_id="id",
            client_secret="sec",
            country="UG",
            currency="UGX",
            environment="production",
            pin="!!!not-base64!!!",
        )
    with pytest.raises(ValueError, match="too short"):
        AirtelConfig(
            client_id="id",
            client_secret="sec",
            country="UG",
            currency="UGX",
            environment="production",
            pin=base64.b64encode(b"short").decode("ascii"),
        )
    with pytest.raises(ValueError, match="public_key_pem"):
        encrypt_airtel_pin("1234", "")

    with (
        patch("importlib.import_module", side_effect=ModuleNotFoundError("no crypto")),
        pytest.raises(RuntimeError, match="Install 'cryptography'"),
    ):
        encrypt_airtel_pin("1234", "-----BEGIN PUBLIC KEY-----")

    class _FakeRSAPub:
        def encrypt(self, plaintext: bytes, padding_obj: object) -> bytes:
            assert plaintext == b"1234"
            assert padding_obj is not None
            return b"E" * 128

    fake_serialization = types.SimpleNamespace(
        load_pem_public_key=lambda data: _FakeRSAPub()
    )
    fake_padding = types.SimpleNamespace(PKCS1v15=lambda: "pkcs1")
    fake_rsa = types.SimpleNamespace(RSAPublicKey=_FakeRSAPub)
    mod_map = {
        "cryptography.hazmat.primitives.serialization": fake_serialization,
        "cryptography.hazmat.primitives.asymmetric.padding": fake_padding,
        "cryptography.hazmat.primitives.asymmetric.rsa": fake_rsa,
    }
    with patch("importlib.import_module", side_effect=lambda name: mod_map[name]):
        enc = encrypt_airtel_pin("1234", "-----BEGIN PUBLIC KEY-----")
        assert base64.b64decode(enc) == b"E" * 128

    # 2. Async Paystack, Flutterwave, and Orange Money provider flows
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transaction/initialize",
        json={
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/async",
                "reference": "ps-async-1",
            },
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transfer",
        json={"status": True, "data": {"reference": "ps-atr-1", "status": "pending"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.paystack.co/transfer/verify/ps-atr-1",
        json={
            "status": True,
            "data": {"status": "success", "amount": 1000, "currency": "NGN"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.flutterwave.com/v3/payments",
        json={"status": "success", "data": {"link": "https://flw.test/async"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.flutterwave.com/v3/transfers",
        json={
            "status": "success",
            "data": {"id": 551, "reference": "flw-atr-1", "status": "NEW"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/transfers/551",
        json={"status": "success", "data": {"id": 551, "status": "SUCCESSFUL"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/oauth/v3/token",
        json={"access_token": "om-atok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/ci/v1/webpayment",
        json={"pay_token": "om-apay", "payment_url": "https://om.ci/1"},
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/ci/v1/transactionstatus",
        json={"status": "SUCCESS"},
        status_code=200,
    )

    async with (
        AsyncPaystackClient(
            PaystackConfig(
                secret_key="sk_test",
                default_customer_email="buyer@example.test",
            )
        ) as ps_client,
        AsyncFlutterwaveClient(
            FlutterwaveConfig(
                secret_key="FLWSECK",
                default_customer_email="buyer@example.test",
                default_account_bank="MPS",
                redirect_url="https://callback.example.test/flw",
            )
        ) as flw_client,
        AsyncOrangeMoneyClient(
            OrangeMoneyConfig(
                client_id="id",
                client_secret="sec",
                merchant_key="mk",
                api_path_prefix="/orange-money-webpay/ci/v1",
                notif_url="https://callback.example.test/om",
            )
        ) as om_client,
    ):
        ps = AsyncPaystackProvider(ps_client)
        assert (
            await ps.collect(
                PaymentRequest(
                    amount="10.00", currency="NGN", payer_msisdn="2348012345678"
                )
            )
        ).reference_id == "ps-async-1"
        assert (
            await ps.disburse(
                DisbursementRequest(
                    amount="10.00", currency="NGN", payee_msisdn="RCP_99"
                )
            )
        ).is_pending()
        assert (await ps.get_status("ps-atr-1", kind="disbursement")).is_successful()

        flw = AsyncFlutterwaveProvider(flw_client)
        assert (
            await flw.collect(
                PaymentRequest(
                    amount="20",
                    currency="KES",
                    payer_msisdn="254712345678",
                    reference_id="flw-acol-1",
                )
            )
        ).checkout_url == "https://flw.test/async"
        assert (
            await flw.disburse(
                DisbursementRequest(
                    amount="20", currency="KES", payee_msisdn="254712345678"
                )
            )
        ).reference_id == "551"
        assert (await flw.get_status("551", kind="disbursement")).is_successful()

        om = AsyncOrangeMoneyProvider(om_client)
        await om.collect(
            PaymentRequest(
                amount="300",
                currency="XOF",
                payer_msisdn="2250701234567",
                reference_id="ord-ci-1",
            )
        )
        assert (await om.get_status("om-apay")).is_successful()


@pytest.mark.asyncio
async def test_async_webhook_parity_mtn_callback_and_active_guard(
    httpx_mock: HTTPXMock,
) -> None:
    """Test #63 async webhook methods, MtnMomoProvider callback_url/external_id, and active bool check."""
    import time

    from py_momo_sdk import (
        AirtelConfig,
        AsyncAirtelClient,
        AsyncWaveClient,
        MtnMomoProvider,
        ProductConfig,
        PyMomoSDK,
        PyMomoSDKConfig,
        PyMomoSDKError,
        WaveConfig,
    )

    payload = b'{"id":"evt-1"}'
    ts = int(time.time())
    wave_sig = hmac.new(
        b"wave-wh-sec", f"{ts}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    ps_sig = hmac.new(b"ps-sec", payload, hashlib.sha512).hexdigest()

    async with (
        AsyncWaveClient(WaveConfig(api_key="wk", webhook_secret="wave-wh-sec")) as aw,
        AsyncPaystackClient(PaystackConfig(secret_key="ps-sec")) as aps,
        AsyncFlutterwaveClient(
            FlutterwaveConfig(secret_key="flw-sec", webhook_hash="flw-h")
        ) as aflw,
        AsyncAirtelClient(
            AirtelConfig(
                client_id="id",
                client_secret="sec",
                country="UG",
                currency="UGX",
                max_retries=1,
                retry_backoff=0.01,
            )
        ) as aairtel,
    ):
        aw.verify_webhook(payload, f"t={ts},v1={wave_sig}")
        aps.verify_webhook(payload, ps_sig)
        aflw.verify_webhook_hash("flw-h")
        assert aairtel._owns_client is True

    # MtnMomoProvider forwards callback_url and returns matching external_id, and active check rejects non-bool
    ref = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
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
        status_code=202,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/accountholder/msisdn/256771234567/active",
        json={"result": 123},
        status_code=200,
    )
    mtn_cfg = PyMomoSDKConfig(
        collection=ProductConfig(
            subscription_key="sub",
            api_user="f47ac10b-58cc-4372-a567-0e02b2c3d479",
            api_key="key",
        )
    )
    with PyMomoSDK(mtn_cfg) as mtn_client:
        mp = MtnMomoProvider(mtn_client)
        res = mp.collect(
            PaymentRequest(
                amount="100",
                currency="EUR",
                payer_msisdn="256771234567",
                reference_id=ref,
                callback_url="https://callback.example.test/mtn-override",
            )
        )
        assert res.external_id == ref
        pay_req = next(
            r
            for r in httpx_mock.get_requests()
            if r.url.path == "/collection/v1_0/requesttopay"
        )
        assert (
            pay_req.headers["X-Callback-Url"]
            == "https://callback.example.test/mtn-override"
        )
        with pytest.raises(PyMomoSDKError, match="boolean 'result'"):
            mtn_client.collection.is_account_holder_active("256771234567")
