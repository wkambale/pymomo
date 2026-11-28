# Multi-provider orchestration

Py MoMo SDK includes a unified provider abstraction and thread-safe routing layer (`PaymentRouter` and `AsyncPaymentRouter`) so applications can integrate seven African mobile money rails and payment gateways behind one normalized interface.

## Supported provider adapters

| Provider | Sync adapter | Async adapter | Capabilities |
| --- | --- | --- | --- |
| MTN MoMo | `MtnMomoProvider` | `AsyncMtnMomoProvider` | Collection, disbursement, balance, preapprovals, delivery notifications |
| Airtel Money | `AirtelMoneyProvider` | `AsyncAirtelMoneyProvider` | Collection, refunds, disbursement, KYC lookup, balance, Base64 HMAC webhooks |
| Wave | `WaveProvider` | `AsyncWaveProvider` | Checkout, refunds, expiry, payouts, reversals, `client_reference` search, `Wave-Signature` request/webhook signing |
| M-Pesa (Daraja) | `MpesaProvider` | `AsyncMpesaProvider` | STK Push (`254` MSISDN normalization), STK query, B2C v3, status/balance/reversal, `SecurityCredential` encryption, callback parsers |
| Paystack | `PaystackProvider` | `AsyncPaystackProvider` | Checkout, direct mobile money charge, refunds, transfer recipients, transfers (`16`–`50` char refs), multi-currency balance, SHA-512 webhooks |
| Flutterwave | `FlutterwaveProvider` | `AsyncFlutterwaveProvider` | Standard payments, direct mobile money charge, ID/ref verification, refunds, transfers & reference reconciliation, currency balance |
| Orange Money | `OrangeMoneyProvider` | `AsyncOrangeMoneyProvider` | Web payment checkout, `OrangePaymentContextStore` (`notif_token` + context), `notif_url` verification, transaction status |

## Routing payments across providers

Register provider adapters with `PaymentRouter` (or `AsyncPaymentRouter`) and manage router lifecycles with `with` / `async with` so all underlying HTTP pools close cleanly. Pass `custom_carrier_prefixes` to override or extend MSISDN prefix detection.

By default, `fallback=True` fails over only on unambiguous pre-flight authentication or missing-credential errors (`AuthenticationError`, `MissingCredentialsError`) so ambiguous `5xx` responses never silently double-charge a subscriber. Set `allow_ambiguous_write_fallback=True` only when downstream reconciliation across rails is in place. During multi-provider routing, `PaymentRouter` automatically adapts `reference_id` formats to satisfy each candidate rail (`<=30` chars for Orange `order_id`, deterministic RFC 4122 UUID v4 for MTN MoMo, `16`–`50` lowercase `[a-z0-9_-]` chars for Paystack transfers, `<=64` chars for Airtel Money) while preserving your original merchant reference in `external_id`:

```python
from py_momo_sdk import (
    AirtelClient,
    AirtelConfig,
    AirtelMoneyProvider,
    MtnMomoProvider,
    PaymentRequest,
    PaymentRouter,
    ProductConfig,
    PyMomoSDK,
    PyMomoSDKConfig,
    WaveClient,
    WaveConfig,
    WaveProvider,
)

mtn_client = PyMomoSDK(
    PyMomoSDKConfig(
        environment="sandbox",
        collection=ProductConfig(
            subscription_key="your-mtn-key",
            api_user="550e8400-e29b-41d4-a716-446655440000",
            api_key="your-mtn-secret",
        ),
    )
)
airtel_client = AirtelClient(
    AirtelConfig(
        client_id="your-airtel-id",
        client_secret="your-airtel-secret",
        country="UG",
        currency="UGX",
    )
)
wave_client = WaveClient(
    WaveConfig(
        api_key="your-wave-api-key",
        success_url="https://your-app.com/wave/success",
        error_url="https://your-app.com/wave/error",
    )
)

with PaymentRouter(
    [
        MtnMomoProvider(mtn_client),
        AirtelMoneyProvider(airtel_client),
        WaveProvider(wave_client),
    ],
    custom_carrier_prefixes={"22176": ("SN", "wave")},
) as router:
    # Routes 25677... automatically to mtn_momo; safe pre-flight failover enabled
    result = router.collect(
        PaymentRequest(
            amount="5000",
            currency="UGX",
            payer_msisdn="256771234567",
            external_id="order-1001",
        ),
        fallback=True,
    )
    print(result.provider, result.status, result.reference_id)

    # Opt-in reconciliation-safe failover across ambiguous 5xx responses
    failover_res = router.collect(
        PaymentRequest(
            amount="5000",
            currency="UGX",
            payer_msisdn="256771234567",
            external_id="order-1002",
        ),
        fallback=True,
        allow_ambiguous_write_fallback=True,
    )
    print(failover_res.raw.get("prior_failed_attempts"))
```

## Provider-specific options and standalone clients

### Wave

Configure `signing_secret` on `WaveConfig` to attach fresh `Wave-Signature: t=<ts>,v1=<hmac>` headers across every Wave `GET` and `POST` request (including retries). `WaveClient` supports checkout session refunds and expiry, payout reversals, and `client_reference` search endpoints (which `WaveProvider.get_status()` also uses automatically when reconciling non-`cos-` / non-`pt-` merchant references after network timeouts):

```python
from py_momo_sdk import WaveClient, WaveConfig, WaveProvider

with WaveClient(
    WaveConfig(
        api_key="your-wave-api-key",
        signing_secret="your-wave-api-signing-secret",
        webhook_secret="your-wave-webhook-secret",
        success_url="https://your-app.com/wave/success",
        error_url="https://your-app.com/wave/error",
    )
) as wave_client:
    session = wave_client.create_checkout_session(
        amount="1500",
        currency="XOF",
        client_reference="wave-order-1001",
    )
    matches = wave_client.search_checkout_sessions("wave-order-1001")
    wave_client.expire_checkout_session(session.id)
    # Completed sessions and payouts can be refunded or reversed:
    # wave_client.refund_checkout_session(session.id)
    # wave_client.reverse_payout("pt-12345")
    # payouts = wave_client.search_payouts("wave-payout-1001")

    provider = WaveProvider(wave_client)
    reconciled = provider.get_status("wave-order-1001", kind="collection")
    print(len(matches), reconciled.status)
```

### Safaricom M-Pesa (Daraja)

M-Pesa Daraja enforces whole-integer `KES` amounts, normalizes Kenyan local numbers (`07...`, `01...`, `+254...`) to `254XXXXXXXXX`, validates `remarks` (`2`–`100` chars) and `occasion` (`0`–`100` chars), generates East Africa Time (`UTC+3`) STK passwords, and provides `encrypt_mpesa_security_credential()`, `query_transaction_status()`, `query_account_balance()`, `reverse_transaction()`, `parse_mpesa_stk_callback()`, and `parse_mpesa_b2c_callback()`:

```python
from pathlib import Path
from py_momo_sdk import (
    MpesaClient,
    MpesaConfig,
    MpesaProvider,
    PaymentRequest,
    encrypt_mpesa_security_credential,
    parse_mpesa_b2c_callback,
    parse_mpesa_stk_callback,
)

# Encrypt initiator password with Safaricom's X.509 certificate (requires cryptography extra)
cert_pem = Path("ProductionCertificate.cer").read_text(encoding="utf-8")
security_credential = encrypt_mpesa_security_credential("initiator-password", cert_pem)

with MpesaClient(
    MpesaConfig(
        consumer_key="your-consumer-key",
        consumer_secret="your-consumer-secret",
        short_code="174379",
        passkey="your-daraja-passkey",
        initiator_name="apiop",
        security_credential=security_credential,
        callback_url="https://your-app.com/mpesa/callback",
        queue_timeout_url="https://your-app.com/mpesa/timeout",
        transaction_type="CustomerPayBillOnline",
    )
) as mpesa_client:
    provider = MpesaProvider(mpesa_client)
    res = provider.collect(
        PaymentRequest(
            amount="100",
            currency="KES",
            payer_msisdn="0712345678",  # Normalized to 254712345678
            external_id="invoice-ke-1",
        )
    )
    status_ack = mpesa_client.query_transaction_status("OEI2AK4Q16", remarks="Order check")
    balance_ack = mpesa_client.query_account_balance(remarks="Float check")
    reversal_ack = mpesa_client.reverse_transaction("OEI2AK4Q16", "100", remarks="Duplicate")
    print(res.reference_id, status_ack.conversation_id, balance_ack.conversation_id, reversal_ack.conversation_id)

# Parse incoming Daraja STK Push and B2C / async ResultURL callbacks into PaymentResult
stk_result = parse_mpesa_stk_callback(
    {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "29115-34620561-1",
                "CheckoutRequestID": "ws_CO_191220191020363925",
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
            }
        }
    }
)
b2c_result = parse_mpesa_b2c_callback(
    {
        "Result": {
            "ResultType": 0,
            "ResultCode": 0,
            "ResultDesc": "The service request is processed successfully.",
            "OriginatorConversationID": "orig-1001",
            "ConversationID": "AG_2026_0001",
            "TransactionID": "OEI2AK4Q16",
        }
    }
)
print(stk_result.status, b2c_result.provider_transaction_id)
```

### Paystack and Flutterwave

Paystack and Flutterwave require a payer email on checkout (`PaymentRequest.payer_email` or `default_customer_email` on config). For Paystack disbursements, create a recipient code (`RCP_...`) first via `create_transfer_recipient()` (discovering bank/mobile-money codes with `list_banks()`) and supply a `16`–`50` character lowercase `[a-z0-9_-]` transfer reference when calling `initiate_transfer()` or `PaystackProvider.disburse()`. Both clients also expose direct mobile money push charges, refunds, and reference-based transfer reconciliation (`FlutterwaveProvider.get_status(..., kind="disbursement")` automatically calls `get_transfer_by_reference()` when passed a non-numeric merchant reference):

```python
from py_momo_sdk import (
    DisbursementRequest,
    FlutterwaveClient,
    FlutterwaveConfig,
    FlutterwaveProvider,
    PaymentRequest,
    PaystackClient,
    PaystackConfig,
    PaystackProvider,
)

with PaystackClient(
    PaystackConfig(
        secret_key="sk_test_your_key",
        default_customer_email="billing@example.com",
    )
) as ps_client:
    ps = PaystackProvider(ps_client)
    banks = ps_client.list_banks(country="ghana", currency="GHS", bank_type="mobile_money")
    recipient = ps_client.create_transfer_recipient(
        recipient_type="mobile_money",
        name="Ama Mensah",
        account_number="0551234987",
        bank_code="MTN",
        currency="GHS",
    )
    recipient_code = recipient["data"]["recipient_code"]

    checkout = ps.collect(
        PaymentRequest(
            amount="250.00",
            currency="NGN",
            payer_msisdn="2348012345678",
            payer_email="customer@example.com",
            external_id="ps-order-1",
        )
    )
    direct_momo = ps_client.charge_mobile_money(
        email="customer@example.com",
        amount="50.00",
        currency="GHS",
        phone="0551234987",
        provider="mtn",
        reference="ps-momo-charge-0001",
    )
    payout = ps.disburse(
        DisbursementRequest(
            amount="50.00",
            currency="GHS",
            payee_msisdn="233551234987",
            payee_bank_code=recipient_code,
            reference_id="trf_payout_2026_0001",  # 16-50 lowercase [a-z0-9_-] chars
        )
    )
    transfer_info = ps_client.verify_transfer("trf_payout_2026_0001")
    refund_info = ps_client.create_refund(checkout.reference_id, amount="250.00", currency="NGN")
    ngn_balance = ps.get_balance(currency="NGN")
    print(
        len(banks.get("data", [])),
        direct_momo["status"],
        payout.reference_id,
        transfer_info["status"],
        refund_info["status"],
        ngn_balance.available_balance,
    )

with FlutterwaveClient(
    FlutterwaveConfig(
        secret_key="FLWSECK_TEST-your-key",
        default_customer_email="billing@example.com",
        default_account_bank="MPS",
    )
) as flw_client:
    flw = FlutterwaveProvider(flw_client)
    momo_charge = flw_client.charge_mobile_money(
        charge_type="mobile_money_uganda",
        amount="1500",
        currency="UGX",
        phone_number="256771234567",
        network="MTN",
        tx_ref="flw-momo-1001",
    )
    verified_by_id = flw_client.verify_transaction_by_id(momo_charge["data"]["id"])
    refund_res = flw_client.refund_transaction(momo_charge["data"]["id"], amount="1500")

    payout = flw.disburse(
        DisbursementRequest(
            amount="1000",
            currency="UGX",
            payee_msisdn="256771234567",
            payee_bank_code="MPS",
            external_id="flw-payout-1",
        )
    )
    transfer_status = flw_client.get_transfer(payout.reference_id)
    by_ref = flw_client.get_transfer_by_reference("flw-payout-1")
    reconciled_payout = flw.get_status("flw-payout-1", kind="disbursement")
    ugx_balance = flw.get_balance(currency="UGX")
    print(
        verified_by_id["status"],
        refund_res["status"],
        transfer_status["status"],
        by_ref["status"],
        reconciled_payout.status,
        ugx_balance.available_balance,
    )
```

### Orange Money

Configure country-specific Orange Money paths via `OrangeMoneyConfig.api_path_prefix` (for example `"/orange-money-webpay/ci/v1"` or `"/orange-money-webpay/sn/v1"`). In multi-worker deployments, inject a shared `OrangePaymentContextStore` (implementing `get`, `set`, `get_notif_token`, and `set_notif_token`) so both `get_status()` and `verify_webhook_notification()` work across worker processes, or pass `order_id`/`amount`/`currency` and `expected_notif_token` explicitly:

```python
from py_momo_sdk import (
    OrangeMoneyClient,
    OrangeMoneyConfig,
    OrangeMoneyProvider,
    OrangePaymentContextStore,
    PaymentRequest,
)


class InMemorySharedOrangeStore(OrangePaymentContextStore):
    def __init__(self) -> None:
        self._ctx: dict[str, tuple[str, str, str]] = {}
        self._notif: dict[str, str] = {}

    def get(self, pay_token: str) -> tuple[str, str, str] | None:
        return self._ctx.get(pay_token)

    def set(self, pay_token: str, order_id: str, amount: str, currency: str) -> None:
        self._ctx[pay_token] = (order_id, amount, currency)

    def get_notif_token(self, pay_token: str) -> str | None:
        return self._notif.get(pay_token)

    def set_notif_token(self, pay_token: str, notif_token: str) -> None:
        self._notif[pay_token] = notif_token


om_cfg = OrangeMoneyConfig(
    client_id="your-orange-client-id",
    client_secret="your-orange-client-secret",
    merchant_key="your-merchant-key",
    api_path_prefix="/orange-money-webpay/sn/v1",
    return_url="https://your-app.com/orange/return",
    cancel_url="https://your-app.com/orange/cancel",
    notif_url="https://your-app.com/orange/webhook",
)
shared_store = InMemorySharedOrangeStore()

with OrangeMoneyClient(om_cfg, context_store=shared_store) as om_client:
    om = OrangeMoneyProvider(om_client)
    res = om.collect(
        PaymentRequest(
            amount="750",
            currency="XOF",
            payer_msisdn="221771234567",
            external_id="om-order-1",
        )
    )
    # Verify incoming notif_url callback payload against stored per-session notif_token
    om_client.verify_webhook_notification(
        {
            "status": "SUCCESS",
            "pay_token": res.reference_id,
            "notif_token": res.raw.get("notif_token", ""),
            "txnid": "MP260101.1234.A00001",
        }
    )
    # Stateless or store-backed status check
    status = om.get_status(
        res.reference_id,
        order_id="om-order-1",
        amount="750",
        currency="XOF",
    )
    print(status.status)
```

## Discovering third-party provider plugins

External packages can register custom adapters via the `py_momo_sdk.providers` entry-point group in `pyproject.toml`. Always pass `allowed_plugins` in production to restrict loading to trusted entry-point names. Set `strict=True` to fail closed if any allowed plugin fails to load, violates the provider protocol, or collides on a duplicate name:

```python
from py_momo_sdk.providers import discover_provider_plugins

plugins = discover_provider_plugins(
    allowed_plugins={"my_custom_gateway"},
    strict=True,
)
print(list(plugins.keys()))
```

Next step: [Review resilience and observability](resilience.md).
