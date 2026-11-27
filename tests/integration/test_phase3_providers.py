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


def test_provider_config_and_input_validation_rules() -> None:
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
        with pytest.raises(ValueError, match=r"(?i)currency"):
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
async def test_async_provider_input_validation_rules() -> None:
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
            return_url="https://callback.example.test/orange/return",
            cancel_url="https://callback.example.test/orange/cancel",
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
        assert st.currency == "XOF"
        status_req = next(
            r
            for r in httpx_mock.get_requests()
            if r.url.path.endswith("/transactionstatus")
        )
        sent_status = json.loads(status_req.read().decode("utf-8"))
        assert sent_status == {
            "order_id": "ord-sn-1",
            "amount": 750,
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
                return_url="https://callback.example.test/om/return",
                cancel_url="https://callback.example.test/om/cancel",
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
        b"wave-wh-sec", f"{ts}".encode() + payload, hashlib.sha256
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


@pytest.mark.asyncio
async def test_phase3_negative_webhooks_path_traversal_payloads_and_not_implemented(
    httpx_mock: HTTPXMock,
) -> None:
    """Test negative webhook verification, path traversal, outbound payloads, and NotImplementedError (#65)."""
    import json
    import time

    from py_momo_sdk import WaveClient, WaveConfig, WebhookVerificationError

    raw = b'{"event":"charge.success","amount":5000}'
    ts = int(time.time())

    # 1. Negative webhook tests across Wave, Paystack, and Flutterwave
    with WaveClient(WaveConfig(api_key="wk", webhook_secret="wave-sec")) as wc:
        valid_sig = hmac.new(
            b"wave-sec", f"{ts}".encode() + raw, hashlib.sha256
        ).hexdigest()
        with pytest.raises(WebhookVerificationError):
            wc.verify_webhook(b"tampered", f"t={ts},v1={valid_sig}")
        with pytest.raises(WebhookVerificationError):
            wc.verify_webhook(raw, f"t={ts - 1000},v1={valid_sig}")
        for bad_seg in ("../admin", "a/b", "id?x=1", "id#frag"):
            with pytest.raises(ValueError, match="Invalid path segment"):
                wc.get_checkout_session(bad_seg)
            with pytest.raises(ValueError, match="Invalid path segment"):
                wc.get_payout(bad_seg)

    with (
        WaveClient(WaveConfig(api_key="wk")) as wc_no_sec,
        pytest.raises(WebhookVerificationError),
    ):
        wc_no_sec.verify_webhook(raw, f"t={ts},v1={'a' * 64}")

    with PaystackClient(PaystackConfig(secret_key="ps-sec")) as psc:
        sha256_downgrade = hmac.new(b"ps-sec", raw, hashlib.sha256).hexdigest()
        with pytest.raises(WebhookVerificationError):
            psc.verify_webhook(raw, sha256_downgrade)
        with pytest.raises(WebhookVerificationError):
            psc.verify_webhook(
                b"tampered", hmac.new(b"ps-sec", raw, hashlib.sha512).hexdigest()
            )
        for bad_seg in ("../verify", "a/b", "   "):
            with pytest.raises(ValueError, match="Invalid path segment"):
                psc.verify_transaction(bad_seg)
            with pytest.raises(ValueError, match="Invalid path segment"):
                psc.verify_transfer(bad_seg)

    with FlutterwaveClient(FlutterwaveConfig(secret_key="flw-sec")) as flw_no_hash:
        with pytest.raises(WebhookVerificationError):
            flw_no_hash.verify_webhook_hash("any-hash")
        for bad_seg in ("../tx", "a/b", "tx?inject=1"):
            with pytest.raises(ValueError, match="Invalid path segment"):
                flw_no_hash.get_transfer(bad_seg)
        for bad_q in ("   ", "bad\r\nref"):
            with pytest.raises(ValueError, match="tx_ref"):
                flw_no_hash.verify_by_reference(bad_q)

    # 2. Outbound payload & header assertions (Paystack minor units, Wave Idempotency-Key, M-Pesa Password)
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transaction/initialize",
        json={"status": True, "data": {"reference": "ps-out-1"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.wave.com/v1/payout",
        json={
            "id": "pt-out-1",
            "amount": "250",
            "currency": "XOF",
            "status": "succeeded",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials",
        json={"access_token": "mp-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
        json={"CheckoutRequestID": "ws_out_1", "ResponseCode": "0"},
        status_code=200,
    )

    with PaystackClient(PaystackConfig(secret_key="ps-sec")) as psc2:
        psc2.initialize_transaction(
            email="user@example.test",
            amount="12.34",
            currency="NGN",
            reference="ps-out-1",
        )
    with WaveClient(WaveConfig(api_key="wk")) as wc2:
        wc2.create_payout(
            amount="250",
            currency="XOF",
            mobile="221 76 123 4567",
            client_reference="wave-ref-99",
        )
    with MpesaClient(
        MpesaConfig(
            consumer_key="ck",
            consumer_secret="cs",
            short_code="174379",
            passkey="pk",
            callback_url="https://callback.example.test/mpesa",
        )
    ) as mpc:
        mpc.stk_push(
            amount="100", phone_number="+254 712 345 678", account_reference="INV-9"
        )
        with pytest.raises(ValueError, match="security_credential"):
            mpc.b2c_transfer(amount="100", phone_number="254712345678")

        mp_prov = MpesaProvider(mpc)
        with pytest.raises(NotImplementedError):
            mp_prov.get_balance()

    reqs = httpx_mock.get_requests()
    ps_req = next(r for r in reqs if r.url.path == "/transaction/initialize")
    assert json.loads(ps_req.read().decode("utf-8"))["amount"] == 1234
    wave_req = next(r for r in reqs if r.url.path == "/v1/payout")
    assert wave_req.headers["Idempotency-Key"] == "wave-ref-99"
    assert "X-Reference-Id" not in wave_req.headers
    wave_body = json.loads(wave_req.read().decode("utf-8"))
    assert wave_body["receive_amount"] == "250"
    assert "amount" not in wave_body
    assert wave_body["mobile"] == "+221761234567"
    stk_req = next(r for r in reqs if r.url.path == "/mpesa/stkpush/v1/processrequest")
    stk_body = json.loads(stk_req.read().decode("utf-8"))
    assert stk_body["BusinessShortCode"] == "174379"
    assert stk_body["PhoneNumber"] == "254712345678"
    assert len(stk_body["Timestamp"]) == 14
    assert stk_body["Password"]

    # 3. NotImplementedError paths on sync/async Orange & async M-Pesa
    with OrangeMoneyClient(
        OrangeMoneyConfig(client_id="id", client_secret="sec", merchant_key="mk")
    ) as omc:
        omp = OrangeMoneyProvider(omc)
        with pytest.raises(NotImplementedError):
            omp.disburse(
                DisbursementRequest(
                    amount="10", currency="XOF", payee_msisdn="221771234567"
                )
            )
        with pytest.raises(NotImplementedError):
            omp.get_balance()

    async with (
        AsyncMpesaClient(
            MpesaConfig(
                consumer_key="ck",
                consumer_secret="cs",
                short_code="174379",
                passkey="pk",
            )
        ) as ampc,
        AsyncOrangeMoneyClient(
            OrangeMoneyConfig(client_id="id", client_secret="sec", merchant_key="mk")
        ) as aomc,
    ):
        with pytest.raises(NotImplementedError):
            await AsyncMpesaProvider(ampc).get_balance()
        with pytest.raises(NotImplementedError):
            await AsyncMpesaProvider(ampc).get_status("AG_1", kind="disbursement")
        aomp = AsyncOrangeMoneyProvider(aomc)
        with pytest.raises(NotImplementedError):
            await aomp.disburse(
                DisbursementRequest(
                    amount="10", currency="XOF", payee_msisdn="221771234567"
                )
            )
        with pytest.raises(NotImplementedError):
            await aomp.get_balance()
        with pytest.raises(NotImplementedError):
            await aomp.get_status("pay-1", kind="disbursement")


@pytest.mark.asyncio
async def test_mpesa_daraja_protocol_fixes(httpx_mock: HTTPXMock) -> None:
    """Verify Issue #85: EAT timestamp, integer Amount, B2C v3 OriginatorConversationID, BuyGoods/CommandID, retries, and validation."""
    import base64
    import json
    from datetime import datetime, timedelta, timezone

    from py_momo_sdk.providers.mpesa import _build_stk_password
    from py_momo_sdk.telemetry import (
        RequestTelemetryEvent,
        TelemetryHook,
        WebhookTelemetryEvent,
    )

    # 1. EAT (UTC+3) timestamp in _build_stk_password
    eat_before = datetime.now(timezone(timedelta(hours=3)))
    password, ts = _build_stk_password("174379", "secret-passkey")
    eat_after = datetime.now(timezone(timedelta(hours=3)))
    parsed_ts = datetime.strptime(ts, "%Y%m%d%H%M%S").replace(
        tzinfo=timezone(timedelta(hours=3))
    )
    assert (
        eat_before - timedelta(seconds=2)
        <= parsed_ts
        <= eat_after + timedelta(seconds=2)
    )
    decoded_pw = base64.b64decode(password).decode("utf-8")
    assert decoded_pw == f"174379secret-passkey{ts}"

    # 2. Config validation: consumer_key ':', transaction_type, command_id, queue_timeout_url, party_b
    with pytest.raises(ValueError, match="consumer_key"):
        MpesaConfig(
            consumer_key="bad:key",
            consumer_secret="cs",
            short_code="174379",
            passkey="pk",
        )
    with pytest.raises(ValueError, match="transaction_type"):
        MpesaConfig(
            consumer_key="ck",
            consumer_secret="cs",
            short_code="174379",
            passkey="pk",
            transaction_type="InvalidType",
        )
    with pytest.raises(ValueError, match="command_id"):
        MpesaConfig(
            consumer_key="ck",
            consumer_secret="cs",
            short_code="174379",
            passkey="pk",
            command_id="UnknownCommand",
        )
    with pytest.raises(ValueError, match="HTTPS"):
        MpesaConfig(
            consumer_key="ck",
            consumer_secret="cs",
            short_code="174379",
            passkey="pk",
            queue_timeout_url="http://insecure.example.test/timeout",
        )

    # 3. Sync STK Push (BuyGoods + party_b + integer Amount + telemetry), retryable STK Query, and B2C v3 (OriginatorConversationID + SalaryPayment + separate QueueTimeOutURL)
    events: list[tuple[str, str, int | None]] = []

    class _Hook(TelemetryHook):
        def on_request(self, event: RequestTelemetryEvent) -> None:
            events.append(("req", event.path, event.status_code))

        def on_webhook(self, event: WebhookTelemetryEvent) -> None:
            events.append(("wh", event.provider, None))

    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials",
        json={"access_token": "tok-85", "expires_in": "3599"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
        json={"CheckoutRequestID": "ws_CO_85", "ResponseCode": "0"},
        status_code=200,
    )
    # First stk_query returns 503, second succeeds (verifies idempotent=True retry)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
        json={"errorMessage": "Temporary unavailable"},
        status_code=503,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
        json={"CheckoutRequestID": "ws_CO_85", "ResultCode": "0", "ResultDesc": "OK"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/b2c/v3/paymentrequest",
        json={
            "ConversationID": "AG_85",
            "OriginatorConversationID": "orig-85",
            "ResponseCode": "0",
        },
        status_code=200,
    )

    cfg = MpesaConfig(
        consumer_key="ck",
        consumer_secret="cs",
        short_code="174379",
        passkey="pk",
        callback_url="https://callback.example.test/mpesa/result",
        queue_timeout_url="https://callback.example.test/mpesa/timeout",
        security_credential="sec-cred",
        transaction_type="CustomerBuyGoodsOnline",
        party_b="998877",
        command_id="SalaryPayment",
        max_retries=1,
        retry_backoff=0.001,
        telemetry=_Hook(),
    )
    with MpesaClient(cfg) as client:
        # Reject fractional amount, >12 char AccountReference, empty checkout_request_id
        with pytest.raises(ValueError, match="whole integer"):
            client.stk_push(amount="100.50", phone_number="254712345678")
        with pytest.raises(ValueError, match="12 characters"):
            client.stk_push(
                amount="100",
                phone_number="254712345678",
                account_reference="THIS-IS-LONGER-THAN-12",
            )
        with pytest.raises(ValueError, match="checkout_request_id"):
            client.stk_query("   ")
        with pytest.raises(ValueError, match="whole integer"):
            client.b2c_transfer(amount="50.25", phone_number="254712345678")

        # Whole-number decimal string "100.00" is normalized to integer 100
        provider = MpesaProvider(client)
        assert provider.capabilities.currencies == ("KES",)
        with pytest.raises(ValueError, match="KES only"):
            provider.collect(
                PaymentRequest(
                    amount="100", currency="TZS", payer_msisdn="254712345678"
                )
            )
        with pytest.raises(ValueError, match="KES only"):
            provider.disburse(
                DisbursementRequest(
                    amount="100", currency="UGX", payee_msisdn="254712345678"
                )
            )

        # Provider truncates 36-char UUID external_id safely to <=12 chars for AccountReference
        col = provider.collect(
            PaymentRequest(
                amount="100.00",
                currency="KES",
                payer_msisdn="254712345678",
                external_id="12345678-1234-4123-8123-1234567890ab",
            )
        )
        assert col.reference_id == "ws_CO_85"

        q_res = provider.get_status("ws_CO_85")
        assert q_res.is_successful()

        disb = provider.disburse(
            DisbursementRequest(
                amount="250.00",
                currency="KES",
                payee_msisdn="254712345678",
                reference_id="orig-85",
                external_id="payroll-1",
            )
        )
        assert disb.reference_id == "AG_85"

    reqs = httpx_mock.get_requests()
    stk_req = next(r for r in reqs if r.url.path == "/mpesa/stkpush/v1/processrequest")
    stk_body = json.loads(stk_req.read().decode("utf-8"))
    assert stk_body["Amount"] == 100
    assert isinstance(stk_body["Amount"], int)
    assert stk_body["TransactionType"] == "CustomerBuyGoodsOnline"
    assert stk_body["BusinessShortCode"] == "174379"
    assert stk_body["PartyB"] == "998877"
    assert stk_body["AccountReference"] == "12345678-123"
    assert len(stk_body["AccountReference"]) == 12

    query_reqs = [r for r in reqs if r.url.path == "/mpesa/stkpushquery/v1/query"]
    assert len(query_reqs) == 2

    b2c_req = next(r for r in reqs if r.url.path == "/mpesa/b2c/v3/paymentrequest")
    b2c_body = json.loads(b2c_req.read().decode("utf-8"))
    assert b2c_body["OriginatorConversationID"] == "orig-85"
    assert b2c_body["CommandID"] == "SalaryPayment"
    assert b2c_body["Amount"] == 250
    assert isinstance(b2c_body["Amount"], int)
    assert b2c_body["QueueTimeOutURL"] == "https://callback.example.test/mpesa/timeout"
    assert b2c_body["ResultURL"] == "https://callback.example.test/mpesa/result"
    assert any(
        ev[0] == "req" and ev[1] == "/mpesa/b2c/v3/paymentrequest" and ev[2] == 200
        for ev in events
    )

    # 4. Async client parity: auto-generated OriginatorConversationID, integer Amount, BuyGoods override
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials",
        json={"access_token": "tok-async-85", "expires_in": "3599"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
        json={"CheckoutRequestID": "ws_CO_async_85", "ResponseCode": "0"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/b2c/v3/paymentrequest",
        json={
            "ConversationID": "AG_async_85",
            "OriginatorConversationID": "auto-oc",
            "ResponseCode": "0",
        },
        status_code=200,
    )

    async with AsyncMpesaClient(cfg) as aclient:
        with pytest.raises(ValueError, match="whole integer"):
            await aclient.stk_push(amount="10.99", phone_number="254712345678")
        with pytest.raises(ValueError, match="checkout_request_id"):
            await aclient.stk_query("")

        aprov = AsyncMpesaProvider(aclient)
        with pytest.raises(ValueError, match="KES only"):
            await aprov.collect(
                PaymentRequest(
                    amount="100", currency="ETB", payer_msisdn="254712345678"
                )
            )
        await aclient.stk_push(
            amount="75",
            phone_number="254712345678",
            account_reference="TILL-1",
            transaction_type="CustomerPayBillOnline",
            party_b="555111",
        )
        await aclient.b2c_transfer(
            amount="300",
            phone_number="254712345678",
            command_id="PromotionPayment",
        )

    all_reqs = httpx_mock.get_requests()
    async_stk = [
        r for r in all_reqs if r.url.path == "/mpesa/stkpush/v1/processrequest"
    ][-1]
    async_stk_body = json.loads(async_stk.read().decode("utf-8"))
    assert async_stk_body["Amount"] == 75
    assert async_stk_body["TransactionType"] == "CustomerPayBillOnline"
    assert async_stk_body["PartyB"] == "555111"

    async_b2c = [r for r in all_reqs if r.url.path == "/mpesa/b2c/v3/paymentrequest"][
        -1
    ]
    async_b2c_body = json.loads(async_b2c.read().decode("utf-8"))
    assert async_b2c_body["CommandID"] == "PromotionPayment"
    assert len(async_b2c_body["OriginatorConversationID"]) == 36
    assert async_b2c_body["Amount"] == 300


@pytest.mark.asyncio
async def test_paystack_flutterwave_orange_issue_87_fixes(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify Issue #87 fixes across Flutterwave, Paystack, and Orange Money."""
    import json

    from py_momo_sdk import NormalizedStatus, PyMomoSDKError
    from py_momo_sdk.providers.flutterwave import _map_flw_status
    from py_momo_sdk.providers.paystack import _map_paystack_status, _to_minor_units

    # --- 1. Flutterwave fixes ---
    with pytest.raises(ValueError, match="webhook_hash"):
        FlutterwaveConfig(secret_key="FLWSECK-test", webhook_hash="   ")
    assert _map_flw_status("reversed") == NormalizedStatus.REVERSED

    httpx_mock.add_response(
        method="POST",
        url="https://api.flutterwave.com/v3/transfers",
        json={
            "status": "success",
            "data": {"id": 881, "reference": "flw-iban-1", "status": "NEW"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/transactions/verify_by_reference?tx_ref=INV%2F2026%2F001",
        json={"status": "success", "data": {"status": "reversed", "currency": "UGX"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/balances/UGX",
        json={
            "status": "success",
            "data": {"available_balance": 75000, "currency": "UGX"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/balances/KES",
        json={
            "status": "success",
            "data": {"available_balance": 1200, "currency": "KES"},
        },
        status_code=200,
    )

    with FlutterwaveClient(
        FlutterwaveConfig(
            secret_key="FLWSECK-test",
            default_account_bank="BARCGB22",
            default_currency="UGX",
        )
    ) as flw_client:
        flw_prov = FlutterwaveProvider(flw_client)
        flw_prov.disburse(
            DisbursementRequest(
                amount="500",
                currency="USD",
                payee_msisdn="GB29NWBK60161331926819",
                reference_id="flw-iban-1",
                callback_url="https://callback.example.test/flw-cb",
            )
        )
        st = flw_prov.get_status("INV/2026/001")
        assert st.status == NormalizedStatus.REVERSED
        assert flw_prov.get_balance().currency == "UGX"
        assert flw_prov.get_balance(currency="KES").currency == "KES"

    reqs = httpx_mock.get_requests()
    tr_req = next(r for r in reqs if r.url.path == "/v3/transfers")
    tr_body = json.loads(tr_req.read().decode("utf-8"))
    assert tr_body["account_number"] == "GB29NWBK60161331926819"
    assert tr_body["callback_url"] == "https://callback.example.test/flw-cb"

    # --- 2. Paystack fixes ---
    assert _map_paystack_status("rejected") == NormalizedStatus.FAILED
    assert _map_paystack_status("blocked") == NormalizedStatus.FAILED
    with pytest.raises(ValueError, match="XOF"):
        _to_minor_units("100.50", currency="XOF")
    assert _to_minor_units("100", currency="XOF") == 10000

    # Secret key whitespace stripped so HMAC-SHA512 succeeds
    ps_cfg = PaystackConfig(
        secret_key="  sk_test_strip  ",
        default_customer_email="buyer@example.test",
        default_currency="KES",
    )
    assert ps_cfg.secret_key == "sk_test_strip"
    raw_body = b'{"event":"charge.success"}'
    ps_sig = hmac.new(b"sk_test_strip", raw_body, hashlib.sha512).hexdigest()

    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transaction/initialize",
        json={
            "status": True,
            "data": {"reference": None, "authorization_url": "https://ps/1"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.paystack.co/balance",
        json={
            "status": True,
            "data": [
                {"balance": 100000, "currency": "NGN"},
                {"balance": 45000, "currency": "KES"},
            ],
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.paystack.co/balance",
        json={
            "status": True,
            "data": [
                {"balance": 100000, "currency": "NGN"},
                {"balance": 45000, "currency": "KES"},
            ],
        },
        status_code=200,
    )
    with PaystackClient(ps_cfg) as ps_client:
        ps_client.verify_webhook(raw_body, ps_sig)
        with pytest.raises(ValueError, match="Invalid path segment"):
            ps_client.initialize_transaction(
                email="buyer@example.test",
                amount="10",
                currency="NGN",
                reference="bad/ref",
            )
        with pytest.raises(ValueError, match="XOF"):
            ps_client.initialize_transaction(
                email="buyer@example.test",
                amount="100.50",
                currency="XOF",
            )
        ps_prov = PaystackProvider(ps_client)
        # "reference": None in response must fall back to our sent ref, not literal "None"
        ps_col = ps_prov.collect(
            PaymentRequest(
                amount="100",
                currency="KES",
                payer_msisdn="254712345678",
                reference_id="ps-clean-ref",
            )
        )
        assert ps_col.reference_id == "ps-clean-ref"
        # Multi-currency balance selection (default_currency="KES", then explicit "NGN")
        assert ps_prov.get_balance().currency == "KES"
        assert ps_prov.get_balance(currency="NGN").available_balance == "1000.00"

    # --- 3. Orange Money fixes ---
    with pytest.raises(ValueError, match="api_path_prefix"):
        OrangeMoneyConfig(
            client_id="cid",
            client_secret="csec",
            merchant_key="mk",
            environment="production",
        )
    with pytest.raises(ValueError, match="sandbox"):
        OrangeMoneyConfig(
            client_id="cid",
            client_secret="csec",
            merchant_key="mk",
            environment="production",
            api_path_prefix="/orange-money-webpay/dev/v1",
        )

    # Never fall back return_url / cancel_url to notif_url
    with (
        OrangeMoneyClient(
            OrangeMoneyConfig(
                client_id="cid",
                client_secret="csec",
                merchant_key="mk",
                notif_url="https://callback.example.test/webhook",
            )
        ) as om_missing_urls,
        pytest.raises(ValueError, match="return_url, cancel_url, and notif_url"),
    ):
        om_missing_urls.create_web_payment(amount="500", currency="XOF")

    # Pluggable context store, integer XOF validation, missing pay_token error, stateless get_status, retryable transactionstatus
    shared_store: dict[str, tuple[str, str, str]] = {}

    class _SharedStore:
        def set(
            self, pay_token: str, order_id: str, amount: str, currency: str
        ) -> None:
            shared_store[pay_token] = (order_id, amount, currency)

        def get(self, pay_token: str) -> tuple[str, str, str] | None:
            return shared_store.get(pay_token)

    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/oauth/v3/token",
        json={"access_token": "om-87-tok", "expires_in": 3600},
        status_code=200,
    )
    # Missing/null pay_token response
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/sn/v1/webpayment",
        json={"pay_token": None, "message": "Invalid merchant"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/sn/v1/webpayment",
        json={"pay_token": "pt-87", "payment_url": "https://webpay.orange.sn/87"},
        status_code=201,
    )
    # Retryable 503 then 200 on transactionstatus
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/sn/v1/transactionstatus",
        status_code=503,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/sn/v1/transactionstatus",
        json={"status": "SUCCESS"},
        status_code=200,
    )

    om_prod_cfg = OrangeMoneyConfig(
        client_id="cid",
        client_secret="csec",
        merchant_key="mk",
        environment="production",
        api_path_prefix="/orange-money-webpay/sn/v1",
        return_url="https://callback.example.test/return",
        cancel_url="https://callback.example.test/cancel",
        notif_url="https://callback.example.test/notif",
        lang="fr",
        reference="MyShop",
        max_retries=1,
        retry_backoff=0.001,
    )
    with OrangeMoneyClient(om_prod_cfg, context_store=_SharedStore()) as om_worker_1:
        om_prov_1 = OrangeMoneyProvider(om_worker_1)
        with pytest.raises(ValueError, match="whole-integer"):
            om_worker_1.create_web_payment(amount="100.50", currency="XOF")
        with pytest.raises(PyMomoSDKError, match="missing 'pay_token'"):
            om_prov_1.collect(
                PaymentRequest(
                    amount="500",
                    currency="XOF",
                    payer_msisdn="221771234567",
                    reference_id="ord-bad",
                )
            )
        col = om_prov_1.collect(
            PaymentRequest(
                amount="500",
                currency="XOF",
                payer_msisdn="221771234567",
                reference_id="ord-87",
            )
        )
        assert col.reference_id == "pt-87"

    # Separate worker with empty local memory queries status statelessly (and retries 503)
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/oauth/v3/token",
        json={"access_token": "om-87-tok-2", "expires_in": 3600},
        status_code=200,
    )
    async with AsyncOrangeMoneyClient(om_prod_cfg) as om_worker_2:
        om_prov_2 = AsyncOrangeMoneyProvider(om_worker_2)
        stateless_st = await om_prov_2.get_status(
            "pt-87", order_id="ord-87", amount="500", currency="XOF"
        )
        assert stateless_st.is_successful()
        assert stateless_st.currency == "XOF"

    om_reqs = [
        r for r in httpx_mock.get_requests() if r.url.path.endswith("/webpayment")
    ]
    om_body = json.loads(om_reqs[-1].read().decode("utf-8"))
    assert om_body["amount"] == 500
    assert isinstance(om_body["amount"], int)
    assert om_body["lang"] == "fr"
    assert om_body["reference"] == "MyShop"


@pytest.mark.asyncio
async def test_issue_122_production_disallows_localhost_urls() -> None:
    """Verify Issue #122: production configs/live keys reject localhost HTTP URLs across providers."""
    from py_momo_sdk import PyMomoSDKError, WaveClient, WaveConfig

    # Orange Money production rejects localhost base_url and callback URLs
    with pytest.raises(PyMomoSDKError, match="HTTPS"):
        OrangeMoneyConfig(
            client_id="cid",
            client_secret="csec",
            merchant_key="mk",
            environment="production",
            api_path_prefix="/orange-money-webpay/sn/v1",
            base_url="http://localhost:8000",
        )
    with pytest.raises(ValueError, match="HTTPS"):
        OrangeMoneyConfig(
            client_id="cid",
            client_secret="csec",
            merchant_key="mk",
            environment="production",
            api_path_prefix="/orange-money-webpay/sn/v1",
            notif_url="http://localhost:8000/notif",
        )
    om_prod = OrangeMoneyConfig(
        client_id="cid",
        client_secret="csec",
        merchant_key="mk",
        environment="production",
        api_path_prefix="/orange-money-webpay/sn/v1",
        return_url="https://merchant.example.com/ret",
        cancel_url="https://merchant.example.com/can",
        notif_url="https://merchant.example.com/notif",
    )
    with (
        OrangeMoneyClient(om_prod) as om_sync,
        pytest.raises(ValueError, match="HTTPS"),
    ):
        om_sync.create_web_payment(
            amount="500", currency="XOF", notif_url="http://127.0.0.1/notif"
        )
    async with AsyncOrangeMoneyClient(om_prod) as om_async:
        with pytest.raises(ValueError, match="HTTPS"):
            await om_async.create_web_payment(
                amount="500", currency="XOF", return_url="http://localhost/ret"
            )

    # Wave live key or production environment rejects localhost URLs
    with pytest.raises(PyMomoSDKError, match="HTTPS"):
        WaveConfig(api_key="wave_sn_prod_abc", base_url="http://localhost:8000")
    with pytest.raises(ValueError, match="HTTPS"):
        WaveConfig(
            api_key="wk",
            environment="production",
            success_url="http://localhost:8000/ok",
        )
    with pytest.raises(ValueError, match="sandbox"):
        WaveConfig(api_key="wave_sn_prod_abc", environment="sandbox")
    with (
        WaveClient(WaveConfig(api_key="wave_sn_prod_abc")) as wc,
        pytest.raises(ValueError, match="HTTPS"),
    ):
        wc.create_checkout_session(
            "1000",
            "XOF",
            success_url="http://localhost/ok",
            error_url="https://merchant.example.com/err",
        )

    # Paystack live key or production environment rejects localhost URLs
    with pytest.raises(PyMomoSDKError, match="HTTPS"):
        PaystackConfig(secret_key="sk_live_abc", base_url="http://127.0.0.1:8000")
    with pytest.raises(ValueError, match="HTTPS"):
        PaystackConfig(
            secret_key="sk_test_abc",
            environment="production",
            callback_url="http://localhost:8000/cb",
        )
    with pytest.raises(ValueError, match="sandbox"):
        PaystackConfig(secret_key="sk_live_abc", environment="sandbox")
    with (
        PaystackClient(PaystackConfig(secret_key="sk_live_abc")) as pc,
        pytest.raises(ValueError, match="HTTPS"),
    ):
        pc.initialize_transaction(
            "a@example.com", "100", "NGN", callback_url="http://localhost/cb"
        )

    # Flutterwave live key or production environment rejects localhost URLs
    with pytest.raises(PyMomoSDKError, match="HTTPS"):
        FlutterwaveConfig(
            secret_key="FLWSECK-live-abc", base_url="http://localhost:8000"
        )
    with pytest.raises(ValueError, match="HTTPS"):
        FlutterwaveConfig(
            secret_key="FLWSECK_TEST-abc",
            environment="production",
            redirect_url="http://127.0.0.1/redirect",
        )
    with pytest.raises(ValueError, match="sandbox"):
        FlutterwaveConfig(secret_key="FLWSECK-live-abc", environment="sandbox")
    with FlutterwaveClient(
        FlutterwaveConfig(
            secret_key="FLWSECK-live-abc",
            default_customer_email="a@example.com",
            default_account_bank="MPS",
        )
    ) as fc:
        with pytest.raises(ValueError, match="HTTPS"):
            fc.create_payment(
                "1000", "UGX", "256771234567", redirect_url="http://localhost/r"
            )
        with pytest.raises(ValueError, match="HTTPS"):
            fc.create_transfer(
                "1000", "UGX", "256771234567", callback_url="http://localhost/cb"
            )


@pytest.mark.asyncio
async def test_issue_129_paystack_transfer_and_init_never_auto_retry(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify Issue #129: Paystack POST /transfer and POST /transaction/initialize never auto-retry."""
    from py_momo_sdk import PyMomoSDKServerError

    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transfer",
        json={"status": False, "message": "Upstream gateway timeout"},
        status_code=503,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transaction/initialize",
        json={"status": False, "message": "Service unavailable"},
        status_code=503,
    )

    cfg = PaystackConfig(secret_key="sk_test_129", max_retries=2, retry_backoff=0.001)
    with PaystackClient(cfg) as pc:
        with pytest.raises(PyMomoSDKServerError) as exc_tr:
            pc.initiate_transfer(
                "100", "NGN", "RCP_12345", reference="trf_issue129_sync_01"
            )
        assert exc_tr.value.reference_id == "trf_issue129_sync_01"

    async with AsyncPaystackClient(cfg) as apc:
        with pytest.raises(PyMomoSDKServerError) as exc_init:
            await apc.initialize_transaction(
                "user@example.com",
                "100",
                "NGN",
                reference="init_issue129_async_01",
            )
        assert exc_init.value.reference_id == "init_issue129_async_01"

    # Exactly 1 attempt per endpoint (0 retries despite max_retries=2)
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_issue_132_mpesa_daraja_pending_500_desc_and_apis(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify Issue #132: Daraja 500.001.1001 pending mapping, 13-char TransactionDesc, Daraja APIs, and callbacks."""
    import json

    from py_momo_sdk import (
        AsyncMpesaClient,
        MpesaClient,
        MpesaConfig,
        MpesaProvider,
        NormalizedStatus,
        PaymentRequest,
        PyMomoSDKServerError,
        parse_mpesa_b2c_callback,
        parse_mpesa_stk_callback,
    )

    cfg = MpesaConfig(
        consumer_key="ck",
        consumer_secret="cs",
        short_code="174379",
        passkey="pk",
        callback_url="https://merchant.example.com/mpesa/cb",
        security_credential="enc-sec-cred",
    )

    # 1. TransactionDesc > 13 chars rejected directly; MpesaProvider caps payer_message safely
    with MpesaClient(cfg) as mc, pytest.raises(ValueError, match="13 characters"):
        mc.stk_push("100", "254712345678", transaction_desc="TooLongDescription")

    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials",
        json={"access_token": "mp-tok-132", "expires_in": "3599"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
        json={
            "MerchantRequestID": "mr-132",
            "CheckoutRequestID": "ws_CO_132",
            "ResponseCode": "0",
            "ResponseDescription": "Success",
        },
        status_code=200,
    )
    # Daraja returns HTTP 500 with errorCode 500.001.1001 while STK push is still pending
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
        json={
            "requestId": "req-132",
            "errorCode": "500.001.1001",
            "errorMessage": "The transaction is being processed",
        },
        status_code=500,
    )
    # Genuine non-500.001.1001 HTTP 500 still raises PyMomoSDKServerError
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
        json={"errorCode": "500.001.9999", "errorMessage": "Internal failure"},
        status_code=500,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/transactionstatus/v1/query",
        json={"ConversationID": "AG_TS_1", "ResponseCode": "0"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/accountbalance/v1/query",
        json={"ConversationID": "AG_BAL_1", "ResponseCode": "0"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/reversal/v1/request",
        json={"ConversationID": "AG_REV_1", "ResponseCode": "0"},
        status_code=200,
    )

    with MpesaClient(cfg) as mc:
        prov = MpesaProvider(mc)
        col = prov.collect(
            PaymentRequest(
                amount="250",
                currency="KES",
                payer_msisdn="254712345678",
                payer_message="Longer Than Thirteen Chars",
            )
        )
        assert col.reference_id == "ws_CO_132"
        stk_req = next(
            r
            for r in httpx_mock.get_requests()
            if r.url.path == "/mpesa/stkpush/v1/processrequest"
        )
        assert len(json.loads(stk_req.read().decode("utf-8"))["TransactionDesc"]) <= 13

        st = prov.get_status("ws_CO_132")
        assert st.status == NormalizedStatus.PENDING
        assert "being processed" in (st.reason or "")

        with pytest.raises(PyMomoSDKServerError):
            mc.stk_query("ws_CO_132")

        assert mc.query_transaction_status("NLJ7RT61SV").conversation_id == "AG_TS_1"
        assert mc.query_account_balance().conversation_id == "AG_BAL_1"
        assert mc.reverse_transaction("NLJ7RT61SV", "250").conversation_id == "AG_REV_1"

    # Async parity for 500.001.1001 and Daraja endpoints
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials",
        json={"access_token": "mp-atok-132", "expires_in": "3599"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
        json={
            "errorCode": "500.001.1001",
            "errorMessage": "The transaction is being processed",
        },
        status_code=500,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/transactionstatus/v1/query",
        json={"ConversationID": "AG_TS_2", "ResponseCode": "0"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/accountbalance/v1/query",
        json={"ConversationID": "AG_BAL_2", "ResponseCode": "0"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.safaricom.co.ke/mpesa/reversal/v1/request",
        json={"ConversationID": "AG_REV_2", "ResponseCode": "0"},
        status_code=200,
    )
    async with AsyncMpesaClient(cfg) as amc:
        aq = await amc.stk_query("ws_CO_132")
        assert aq.result_code is None
        assert (
            await amc.query_transaction_status("NLJ7RT61SV")
        ).conversation_id == "AG_TS_2"
        assert (await amc.query_account_balance()).conversation_id == "AG_BAL_2"
        assert (
            await amc.reverse_transaction("NLJ7RT61SV", "250")
        ).conversation_id == "AG_REV_2"

    # Typed callback parsers
    stk_cb = parse_mpesa_stk_callback(
        {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "mr-1",
                    "CheckoutRequestID": "ws_CO_1",
                    "ResultCode": 0,
                    "ResultDesc": "The service request is processed successfully.",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 250},
                            {"Name": "MpesaReceiptNumber", "Value": "NLJ7RT61SV"},
                        ]
                    },
                }
            }
        }
    )
    assert stk_cb.is_successful()
    assert stk_cb.provider_transaction_id == "NLJ7RT61SV"
    assert stk_cb.amount == "250"

    b2c_cb = parse_mpesa_b2c_callback(
        {
            "Result": {
                "ConversationID": "AG_1",
                "OriginatorConversationID": "orig-1",
                "ResultCode": 0,
                "ResultDesc": "Processed",
                "TransactionID": "TXB2C1",
                "ResultParameters": {
                    "ResultParameter": [
                        {"Key": "TransactionAmount", "Value": 500},
                        {"Key": "TransactionReceipt", "Value": "TXB2C1"},
                    ]
                },
            }
        }
    )
    assert b2c_cb.is_successful()
    assert b2c_cb.provider_transaction_id == "TXB2C1"
    assert b2c_cb.amount == "500"


@pytest.mark.asyncio
async def test_issue_133_orange_order_id_limit_notif_token_and_txnid(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify Issue #133: <=30-char default order_id, length limits, notif_token verification, and txnid."""
    import json

    from py_momo_sdk import WebhookVerificationError

    cfg = OrangeMoneyConfig(
        client_id="cid-133",
        client_secret="csec-133",
        merchant_key="mk-133",
        return_url="https://merchant.example.com/ret",
        cancel_url="https://merchant.example.com/can",
        notif_url="https://merchant.example.com/notif",
    )

    # Length bounds enforced for order_id (>30), reference (>30), and URL (>120)
    with pytest.raises(ValueError, match="30 characters"):
        OrangeMoneyConfig(
            client_id="cid",
            client_secret="sec",
            merchant_key="mk",
            reference="R" * 31,
        )
    with pytest.raises(ValueError, match="120 characters"):
        OrangeMoneyConfig(
            client_id="cid",
            client_secret="sec",
            merchant_key="mk",
            notif_url="https://merchant.example.com/" + ("a" * 100),
        )

    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/oauth/v3/token",
        json={"access_token": "om-tok-133", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/dev/v1/webpayment",
        json={
            "status": 201,
            "pay_token": "pt-133-sync",
            "notif_token": "nt-secret-133",
            "payment_url": "https://webpayment.orange.com/pay/pt-133-sync",
        },
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/dev/v1/transactionstatus",
        json={"status": "SUCCESS", "txnid": "OMTX133999"},
        status_code=200,
    )

    with OrangeMoneyClient(cfg) as omc:
        with pytest.raises(ValueError, match="30 characters"):
            omc.create_web_payment("500", "XOF", order_id="o" * 31)

        prov = OrangeMoneyProvider(omc)
        col = prov.collect(
            PaymentRequest(amount="500", currency="XOF", payer_msisdn="221771234567")
        )
        assert col.external_id is not None
        assert len(col.external_id) <= 30

        wp_req = next(
            r for r in httpx_mock.get_requests() if r.url.path.endswith("/webpayment")
        )
        sent_order_id = json.loads(wp_req.read().decode("utf-8"))["order_id"]
        assert len(sent_order_id) <= 30

        # Constant-time notif_token verification using stored token
        omc.verify_webhook_notification(
            {
                "status": "SUCCESS",
                "notif_token": "nt-secret-133",
                "txnid": "OMTX133999",
            },
            pay_token="pt-133-sync",
        )
        with pytest.raises(WebhookVerificationError):
            omc.verify_webhook_notification(
                {"status": "SUCCESS", "notif_token": "wrong-token"},
                pay_token="pt-133-sync",
            )
        with pytest.raises(WebhookVerificationError):
            omc.verify_webhook_notification(
                {"status": "SUCCESS", "notif_token": "nt-secret-133"},
                pay_token="unknown-pay-token",
            )

        # Status maps txnid -> provider_transaction_id
        st = prov.get_status("pt-133-sync")
        assert st.is_successful()
        assert st.provider_transaction_id == "OMTX133999"

    # Async parity
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/oauth/v3/token",
        json={"access_token": "om-atok-133", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/dev/v1/webpayment",
        json={
            "status": 201,
            "pay_token": "pt-133-async",
            "notif_token": "nt-async-133",
            "payment_url": "https://webpayment.orange.com/pay/pt-133-async",
        },
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.orange.com/orange-money-webpay/dev/v1/transactionstatus",
        json={"status": "SUCCESS", "txnid": "OMTX133ASYNC"},
        status_code=200,
    )
    async with AsyncOrangeMoneyClient(cfg) as aomc:
        aprov = AsyncOrangeMoneyProvider(aomc)
        acol = await aprov.collect(
            PaymentRequest(amount="500", currency="XOF", payer_msisdn="221771234567")
        )
        assert acol.external_id is not None and len(acol.external_id) <= 30
        aomc.verify_webhook_notification(
            {"status": "SUCCESS", "notif_token": "nt-async-133"},
            pay_token="pt-133-async",
        )
        ast = await aprov.get_status("pt-133-async")
        assert ast.provider_transaction_id == "OMTX133ASYNC"


@pytest.mark.asyncio
async def test_issue_134_paystack_transfer_ref_and_endpoints(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify Issue #134: Paystack transfer ref rules, channels, recipients, banks, momo charge, and refunds."""
    import json

    cfg = PaystackConfig(
        secret_key="sk_test_issue134",
        default_customer_email="buyer@example.com",
    )

    with PaystackClient(cfg) as client:
        # Transfer reference must be 16-50 lowercase [a-z0-9_-]
        for bad_ref in (
            "short-ref",
            "UPPERCASE_REF_123456",
            "invalid.dot.ref_1234",
            "a" * 51,
        ):
            with pytest.raises(ValueError, match="16-50 lowercase"):
                client.initiate_transfer("10.00", "GHS", "RCP_123", reference=bad_ref)
        with pytest.raises(ValueError, match="non-empty string"):
            client.initiate_transfer("10.00", "GHS", "RCP_123", reference="   ")

        # Channels validation
        with pytest.raises(ValueError, match="channels"):
            client.initialize_transaction(
                "buyer@example.com", "10.00", "GHS", channels=[]
            )
        with pytest.raises(ValueError, match="channels"):
            client.initialize_transaction(
                "buyer@example.com",
                "10.00",
                "GHS",
                channels="mobile_money",  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError, match="non-empty"):
            client.initialize_transaction(
                "buyer@example.com", "10.00", "GHS", channels=[" "]
            )

        # Validation on new endpoints
        with pytest.raises(ValueError, match="recipient_type"):
            client.create_transfer_recipient("", "Alice", "0551234567", "MTN", "GHS")
        with pytest.raises(ValueError, match="phone"):
            client.charge_mobile_money("buyer@example.com", "10.00", "GHS", "", "mtn")
        with pytest.raises(ValueError, match="provider"):
            client.charge_mobile_money(
                "buyer@example.com", "10.00", "GHS", "0551234567", ""
            )
        with pytest.raises(ValueError, match="transaction"):
            client.create_refund("")

        httpx_mock.add_response(
            method="POST",
            url="https://api.paystack.co/transaction/initialize",
            json={
                "status": True,
                "data": {
                    "authorization_url": "https://checkout.paystack.com/momo134",
                    "reference": "ps_init_134_sync",
                },
            },
            status_code=200,
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.paystack.co/transferrecipient",
            json={
                "status": True,
                "data": {"recipient_code": "RCP_momo134sync"},
            },
            status_code=201,
        )
        httpx_mock.add_response(
            method="GET",
            url="https://api.paystack.co/bank?country=ghana&currency=GHS&type=mobile_money",
            json={
                "status": True,
                "data": [{"name": "MTN", "code": "MTN", "type": "mobile_money"}],
            },
            status_code=200,
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.paystack.co/charge",
            json={
                "status": True,
                "data": {"reference": "ps_charge_134", "status": "send_otp"},
            },
            status_code=200,
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.paystack.co/refund",
            json={"status": True, "data": {"status": "pending"}},
            status_code=200,
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.paystack.co/transfer",
            json={
                "status": True,
                "data": {
                    "reference": "paystack_tr_ref_134_ok",
                    "status": "success",
                },
            },
            status_code=200,
        )

        init_res = client.initialize_transaction(
            "buyer@example.com",
            "50.00",
            "GHS",
            reference="ps_init_134_sync",
            channels=["mobile_money"],
        )
        assert init_res["status"] is True

        rec_res = client.create_transfer_recipient(
            "mobile_money",
            "Alice Mensah",
            "0551234567",
            "MTN",
            "GHS",
            description="Supplier payout",
        )
        assert rec_res["data"]["recipient_code"] == "RCP_momo134sync"

        banks_res = client.list_banks(
            country="ghana", currency="GHS", bank_type="mobile_money"
        )
        assert banks_res["data"][0]["code"] == "MTN"

        charge_res = client.charge_mobile_money(
            "buyer@example.com",
            "25.00",
            "GHS",
            "0551234567",
            "MTN",
            reference="ps_charge_134",
        )
        assert charge_res["data"]["status"] == "send_otp"

        refund_res = client.create_refund(
            "ps_charge_134",
            amount="10.00",
            currency="GHS",
            customer_note="Customer requested refund",
            merchant_note="Partial refund",
        )
        assert refund_res["data"]["status"] == "pending"

        tr_res = client.initiate_transfer(
            "20.00",
            "GHS",
            "RCP_momo134sync",
            reference="paystack_tr_ref_134_ok",
        )
        assert tr_res["data"]["reference"] == "paystack_tr_ref_134_ok"

        reqs = httpx_mock.get_requests()
        init_payload = json.loads(
            next(r for r in reqs if r.url.path == "/transaction/initialize")
            .read()
            .decode("utf-8")
        )
        assert init_payload["channels"] == ["mobile_money"]

        charge_payload = json.loads(
            next(r for r in reqs if r.url.path == "/charge").read().decode("utf-8")
        )
        assert charge_payload["amount"] == 2500
        assert charge_payload["mobile_money"] == {
            "phone": "0551234567",
            "provider": "mtn",
        }

        refund_payload = json.loads(
            next(r for r in reqs if r.url.path == "/refund").read().decode("utf-8")
        )
        assert refund_payload["amount"] == 1000
        assert refund_payload["currency"] == "GHS"

    # Async parity
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transaction/initialize",
        json={
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/momo134a",
                "reference": "ps_init_134_async",
            },
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transferrecipient",
        json={"status": True, "data": {"recipient_code": "RCP_momo134async"}},
        status_code=201,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.paystack.co/bank?country=kenya&currency=KES&type=mobile_money",
        json={"status": True, "data": [{"name": "M-PESA", "code": "MPESA"}]},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/charge",
        json={
            "status": True,
            "data": {"reference": "ps_charge_134_a", "status": "pay_offline"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/refund",
        json={"status": True, "data": {"status": "processed"}},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.paystack.co/transfer",
        json={
            "status": True,
            "data": {
                "reference": "paystack_tr_ref_134_as",
                "status": "success",
            },
        },
        status_code=200,
    )

    async with AsyncPaystackClient(cfg) as aclient:
        with pytest.raises(ValueError, match="16-50 lowercase"):
            await aclient.initiate_transfer(
                "10.00", "KES", "RCP_123", reference="SHORT"
            )
        with pytest.raises(ValueError, match="recipient_type"):
            await aclient.create_transfer_recipient(
                "", "Bob", "0712345678", "MPESA", "KES"
            )
        with pytest.raises(ValueError, match="phone"):
            await aclient.charge_mobile_money(
                "buyer@example.com", "10.00", "KES", "", "mpesa"
            )
        with pytest.raises(ValueError, match="provider"):
            await aclient.charge_mobile_money(
                "buyer@example.com", "10.00", "KES", "0712345678", ""
            )
        with pytest.raises(ValueError, match="transaction"):
            await aclient.create_refund("")

        ainit = await aclient.initialize_transaction(
            "buyer@example.com",
            "50.00",
            "KES",
            reference="ps_init_134_async",
            channels=["mobile_money"],
        )
        assert ainit["status"] is True

        arec = await aclient.create_transfer_recipient(
            "mobile_money",
            "Bob",
            "0712345678",
            "MPESA",
            "KES",
            description="Async payout",
        )
        assert arec["data"]["recipient_code"] == "RCP_momo134async"

        abanks = await aclient.list_banks(
            country="kenya", currency="KES", bank_type="mobile_money"
        )
        assert abanks["data"][0]["code"] == "MPESA"

        acharge = await aclient.charge_mobile_money(
            "buyer@example.com",
            "30.00",
            "KES",
            "0712345678",
            "mpesa",
            reference="ps_charge_134_a",
        )
        assert acharge["data"]["status"] == "pay_offline"

        arefund = await aclient.create_refund(
            "ps_charge_134_a",
            amount="15.00",
            currency="KES",
            customer_note="Customer requested",
            merchant_note="Done",
        )
        assert arefund["data"]["status"] == "processed"

        atr = await aclient.initiate_transfer(
            "20.00",
            "KES",
            "RCP_momo134async",
            reference="paystack_tr_ref_134_as",
        )
        assert atr["data"]["reference"] == "paystack_tr_ref_134_as"


@pytest.mark.asyncio
async def test_issue_135_flutterwave_numeric_transfers_and_momo_endpoints(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify Issue #135: numeric transfer amount, regional fields, direct momo charges, verify by id, refund, and transfer lookup by reference."""
    import json

    cfg = FlutterwaveConfig(
        secret_key="FLWSECK_TEST_135",
        default_customer_email="payer@example.com",
        default_account_bank="MPS",
        redirect_url="https://merchant.example.com/flw-return",
    )

    with FlutterwaveClient(cfg) as client:
        # Input validation checks
        with pytest.raises(ValueError, match="charge_type"):
            client.charge_mobile_money("card", "5000", "UGX", "256771234567")
        with pytest.raises(ValueError, match="charge_type"):
            client.charge_mobile_money(
                "mobile_money_uganda&evil=1", "5000", "UGX", "256771234567"
            )
        with pytest.raises(ValueError, match="transaction_id"):
            client.verify_transaction_by_id(True)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="transaction_id"):
            client.verify_transaction_by_id(0)
        with pytest.raises(ValueError, match="transaction_id"):
            client.refund_transaction("")
        with pytest.raises(ValueError, match="beneficiary_name"):
            client.create_transfer(
                "5000", "UGX", "256771234567", beneficiary_name="   "
            )
        with pytest.raises(ValueError, match="destination_branch_code"):
            client.create_transfer(
                "5000", "UGX", "256771234567", destination_branch_code="  "
            )
        with pytest.raises(ValueError, match="meta"):
            client.create_transfer(
                "5000",
                "UGX",
                "256771234567",
                meta=["not-a-dict"],  # type: ignore[list-item]
            )
        with pytest.raises(ValueError, match="comments"):
            client.refund_transaction(999, comments="  ")

        httpx_mock.add_response(
            method="POST",
            url="https://api.flutterwave.com/v3/transfers",
            json={
                "status": "success",
                "data": {"id": 13501, "reference": "flw-tr-135-sync", "status": "NEW"},
            },
            status_code=200,
        )
        httpx_mock.add_response(
            method="GET",
            url="https://api.flutterwave.com/v3/transfers?reference=flw-tr-135-sync",
            json={
                "status": "success",
                "data": [
                    {
                        "id": 13501,
                        "reference": "flw-tr-135-sync",
                        "status": "SUCCESSFUL",
                    }
                ],
            },
            status_code=200,
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.flutterwave.com/v3/charges?type=mobile_money_uganda",
            json={
                "status": "success",
                "data": {"id": 88135, "tx_ref": "flw-mm-135", "status": "pending"},
            },
            status_code=200,
        )
        httpx_mock.add_response(
            method="GET",
            url="https://api.flutterwave.com/v3/transactions/88135/verify",
            json={
                "status": "success",
                "data": {"id": 88135, "status": "successful", "currency": "UGX"},
            },
            status_code=200,
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.flutterwave.com/v3/transactions/88135/refund",
            json={"status": "success", "data": {"id": 99135, "status": "completed"}},
            status_code=200,
        )

        tr = client.create_transfer(
            "15000",
            "UGX",
            "256771234567",
            reference="flw-tr-135-sync",
            beneficiary_name="Grace Namono",
            destination_branch_code="UG001",
            debit_currency="UGX",
            meta=[{"sender": "Kikuubo Shop", "mobile_number": "256700000001"}],
        )
        assert tr["data"]["id"] == 13501

        reconciled = client.get_transfer_by_reference("flw-tr-135-sync")
        assert reconciled["data"][0]["status"] == "SUCCESSFUL"

        charge = client.charge_mobile_money(
            "mobile_money_uganda",
            "2500.50",
            "KES",
            "+256 771 234 567",
            tx_ref="flw-mm-135",
            network="MTN",
            fullname="Grace Namono",
            country="UG",
        )
        assert charge["data"]["id"] == 88135

        verified = client.verify_transaction_by_id(88135)
        assert verified["data"]["status"] == "successful"

        refunded = client.refund_transaction(
            88135, amount="500.25", comments="Partial customer refund"
        )
        assert refunded["data"]["status"] == "completed"

        reqs = httpx_mock.get_requests()
        tr_body = json.loads(
            next(
                r for r in reqs if r.url.path == "/v3/transfers" and r.method == "POST"
            )
            .read()
            .decode("utf-8")
        )
        assert tr_body["amount"] == 15000
        assert isinstance(tr_body["amount"], int)
        assert tr_body["beneficiary_name"] == "Grace Namono"
        assert tr_body["destination_branch_code"] == "UG001"
        assert tr_body["debit_currency"] == "UGX"
        assert tr_body["meta"] == [
            {"sender": "Kikuubo Shop", "mobile_number": "256700000001"}
        ]

        ch_body = json.loads(
            next(r for r in reqs if r.url.path == "/v3/charges").read().decode("utf-8")
        )
        assert ch_body["amount"] == 2500.5
        assert isinstance(ch_body["amount"], float)
        assert ch_body["phone_number"] == "256771234567"
        assert ch_body["network"] == "MTN"

        rf_body = json.loads(
            next(r for r in reqs if r.url.path == "/v3/transactions/88135/refund")
            .read()
            .decode("utf-8")
        )
        assert rf_body["amount"] == 500.25
        assert rf_body["comments"] == "Partial customer refund"

    # Async parity
    httpx_mock.add_response(
        method="POST",
        url="https://api.flutterwave.com/v3/transfers",
        json={
            "status": "success",
            "data": {"id": 13502, "reference": "flw-tr-135-async", "status": "NEW"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/transfers?reference=flw-tr-135-async",
        json={
            "status": "success",
            "data": [
                {"id": 13502, "reference": "flw-tr-135-async", "status": "SUCCESSFUL"}
            ],
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.flutterwave.com/v3/charges?type=mpesa",
        json={
            "status": "success",
            "data": {"id": 88136, "tx_ref": "flw-mm-135-a", "status": "pending"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.flutterwave.com/v3/transactions/88136/verify",
        json={
            "status": "success",
            "data": {"id": 88136, "status": "successful", "currency": "KES"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.flutterwave.com/v3/transactions/88136/refund",
        json={"status": "success", "data": {"id": 99136, "status": "completed"}},
        status_code=200,
    )

    async with AsyncFlutterwaveClient(cfg) as aclient:
        with pytest.raises(ValueError, match="beneficiary_name"):
            await aclient.create_transfer(
                "100", "KES", "254712345678", beneficiary_name=" "
            )
        with pytest.raises(ValueError, match="destination_branch_code"):
            await aclient.create_transfer(
                "100", "KES", "254712345678", destination_branch_code=" "
            )
        with pytest.raises(ValueError, match="comments"):
            await aclient.refund_transaction("88136", comments=" ")

        atr = await aclient.create_transfer(
            "200.50",
            "KES",
            "254712345678",
            reference="flw-tr-135-async",
            beneficiary_name="John Doe",
            destination_branch_code="KE01",
            debit_currency="KES",
            meta={"sender": "Async Merchant"},
        )
        assert atr["data"]["id"] == 13502

        arec = await aclient.get_transfer_by_reference("flw-tr-135-async")
        assert arec["data"][0]["status"] == "SUCCESSFUL"

        ach = await aclient.charge_mobile_money(
            "mpesa",
            "300",
            "KES",
            "254712345678",
            tx_ref="flw-mm-135-a",
            voucher="V123",
            redirect_url="https://merchant.example.com/cb",
        )
        assert ach["data"]["id"] == 88136

        aver = await aclient.verify_transaction_by_id("88136")
        assert aver["data"]["status"] == "successful"

        aref = await aclient.refund_transaction("88136", amount="100")
        assert aref["data"]["status"] == "completed"
