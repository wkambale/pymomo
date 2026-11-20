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
    flw_cfg = FlutterwaveConfig(secret_key="FLWSECK_TEST", webhook_hash="flw-hash")
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
        client_id="om-id", client_secret="om-sec", merchant_key="om-mk"
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
            )
        ) as mpesa,
        AsyncPaystackClient(PaystackConfig(secret_key="sk_test")) as paystack,
        AsyncFlutterwaveClient(FlutterwaveConfig(secret_key="FLWSECK")) as flw,
        AsyncOrangeMoneyClient(
            OrangeMoneyConfig(
                client_id="om-id", client_secret="om-sec", merchant_key="om-mk"
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
