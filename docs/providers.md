# Multi-provider orchestration

Py MoMo SDK includes a unified provider abstraction and thread-safe routing layer (`PaymentRouter` and `AsyncPaymentRouter`) so applications can integrate seven African mobile money rails and payment gateways behind one normalized interface.

## Supported provider adapters

| Provider | Sync adapter | Async adapter | Capabilities |
| --- | --- | --- | --- |
| MTN MoMo | `MtnMomoProvider` | `AsyncMtnMomoProvider` | Collection, disbursement, balance |
| Airtel Money | `AirtelMoneyProvider` | `AsyncAirtelMoneyProvider` | Collection, disbursement, balance |
| Wave | `WaveProvider` | `AsyncWaveProvider` | Checkout sessions, payouts (`receive_amount`), balance, timestamped `Wave-Signature` |
| M-Pesa (Daraja) | `MpesaProvider` | `AsyncMpesaProvider` | STK Push (PayBill/BuyGoods, EAT timestamps, integer KES), STK query, B2C v3 disbursement |
| Paystack | `PaystackProvider` | `AsyncPaystackProvider` | Checkout, verification, transfers (`verify_transfer()`), multi-currency balance, SHA-512 webhooks |
| Flutterwave | `FlutterwaveProvider` | `AsyncFlutterwaveProvider` | Standard payments, verification, transfers (`get_transfer()`), currency balance, static hash token |
| Orange Money | `OrangeMoneyProvider` | `AsyncOrangeMoneyProvider` | Web payment checkout, stateless or store-backed transaction status |

## Routing payments across providers

Register provider adapters with `PaymentRouter` (or `AsyncPaymentRouter`) and manage router lifecycles with `with` / `async with` so all underlying HTTP pools close cleanly. Pass `custom_carrier_prefixes` to override or extend MSISDN prefix detection.

By default, `fallback=True` fails over only on unambiguous pre-flight authentication or missing-credential errors (`AuthenticationError`, `MissingCredentialsError`) so ambiguous `5xx` responses never silently double-charge a subscriber. Set `allow_ambiguous_write_fallback=True` only when downstream reconciliation across rails is in place; when enabled, the router pre-generates a deterministic `reference_id` and records `prior_failed_attempts` in `result.raw`:

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

### Safaricom M-Pesa (Daraja)

M-Pesa Daraja enforces whole-integer `KES` amounts, East Africa Time (`UTC+3`) STK passwords, optional `transaction_type="CustomerBuyGoodsOnline"` with `party_b`, and mandatory `OriginatorConversationID` on B2C v3 payouts:

```python
from py_momo_sdk import (
    MpesaClient,
    MpesaConfig,
    MpesaProvider,
    PaymentRequest,
)

with MpesaClient(
    MpesaConfig(
        consumer_key="your-consumer-key",
        consumer_secret="your-consumer-secret",
        short_code="174379",
        passkey="your-daraja-passkey",
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
            payer_msisdn="254712345678",
            external_id="invoice-ke-1",
        )
    )
    print(res.reference_id, res.status)
```

### Paystack and Flutterwave

Paystack and Flutterwave require a payer email on checkout (`PaymentRequest.payer_email` or `default_customer_email` on config) and Flutterwave requires a destination bank or mobile-money bank code on disbursements (`DisbursementRequest.payee_bank_code` or `default_account_bank` on config). Both clients also expose direct transfer-verification methods (`PaystackClient.verify_transfer()` and `FlutterwaveClient.get_transfer()`), and `get_balance(currency=...)` selects the exact currency ledger:

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
    checkout = ps.collect(
        PaymentRequest(
            amount="250.00",
            currency="NGN",
            payer_msisdn="2348012345678",
            payer_email="customer@example.com",
            external_id="ps-order-1",
        )
    )
    transfer_info = ps_client.verify_transfer("trf-ref-1")
    ngn_balance = ps.get_balance(currency="NGN")
    print(checkout.reference_id, transfer_info["status"], ngn_balance.available_balance)

with FlutterwaveClient(
    FlutterwaveConfig(
        secret_key="FLWSECK_TEST-your-key",
        default_customer_email="billing@example.com",
        default_account_bank="MPS",
    )
) as flw_client:
    flw = FlutterwaveProvider(flw_client)
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
    ugx_balance = flw.get_balance(currency="UGX")
    print(transfer_status["status"], ugx_balance.available_balance)
```

### Orange Money

Configure country-specific Orange Money paths via `OrangeMoneyConfig.api_path_prefix` (for example `"/orange-money-webpay/ci/v1"` or `"/orange-money-webpay/sn/v1"`). In multi-worker or stateless deployments, either pass `order_id`, `amount`, and `currency` directly to `OrangeMoneyProvider.get_status()` or inject a shared `OrangePaymentContextStore` (such as a Redis-backed implementation):

```python
from py_momo_sdk import (
    OrangeMoneyClient,
    OrangeMoneyConfig,
    OrangeMoneyProvider,
    PaymentRequest,
)

om_cfg = OrangeMoneyConfig(
    client_id="your-orange-client-id",
    client_secret="your-orange-client-secret",
    merchant_key="your-merchant-key",
    api_path_prefix="/orange-money-webpay/sn/v1",
    return_url="https://your-app.com/orange/return",
    cancel_url="https://your-app.com/orange/cancel",
    notif_url="https://your-app.com/orange/webhook",
)

with OrangeMoneyClient(om_cfg) as om_client:
    om = OrangeMoneyProvider(om_client)
    res = om.collect(
        PaymentRequest(
            amount="750",
            currency="XOF",
            payer_msisdn="221771234567",
            external_id="om-order-1",
        )
    )
    # Stateless status check works across restarts and multiple workers
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
