# Multi-provider orchestration

Py MoMo SDK includes a unified provider abstraction and routing layer (`PaymentRouter` and `AsyncPaymentRouter`) so applications can integrate multiple mobile money rails and payment gateways behind one normalized interface.

## Supported provider adapters

| Provider | Sync adapter | Async adapter | Capabilities |
| --- | --- | --- | --- |
| MTN MoMo | `MtnMomoProvider` | `AsyncMtnMomoProvider` | Collection, disbursement, balance, HMAC webhooks |
| Airtel Money | `AirtelMoneyProvider` | `AsyncAirtelMoneyProvider` | Collection, disbursement, balance |
| Wave | `WaveProvider` | `AsyncWaveProvider` | Checkout sessions, payouts, balance, timestamped HMAC |
| M-Pesa (Daraja) | `MpesaProvider` | `AsyncMpesaProvider` | STK Push, STK query, B2C disbursement |
| Paystack | `PaystackProvider` | `AsyncPaystackProvider` | Checkout, verification, transfers, balance, SHA-512 webhooks |
| Flutterwave | `FlutterwaveProvider` | `AsyncFlutterwaveProvider` | Standard payments, verification, transfers, balance, hash token |
| Orange Money | `OrangeMoneyProvider` | `AsyncOrangeMoneyProvider` | Web payment checkout, transaction status |

## Routing payments across providers

Register provider adapters with `PaymentRouter` (or `AsyncPaymentRouter`) to route by MSISDN carrier prefix, explicit provider ID, or automatic `5xx` fallback:

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
wave_client = WaveClient(WaveConfig(api_key="your-wave-api-key"))

router = PaymentRouter(
    [
        MtnMomoProvider(mtn_client),
        AirtelMoneyProvider(airtel_client),
        WaveProvider(wave_client),
    ]
)

# Routes 25677... automatically to mtn_momo and falls back on 5xx errors
result = router.collect(
    PaymentRequest(
        amount="5000.00",
        currency="UGX",
        payer_msisdn="256771234567",
        external_id="order-1001",
    ),
    fallback=True,
)
print(result.provider, result.status, result.reference_id)
```

## Using M-Pesa, Paystack, Flutterwave, and Orange Money

All additional provider clients expose both standalone methods and normalized `PaymentProvider` adapters:

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

## Discovering third-party provider plugins

External packages can register custom adapters via the `py_momo_sdk.providers` entry-point group in `pyproject.toml`:

```python
from py_momo_sdk.providers import discover_provider_plugins

plugins = discover_provider_plugins()
print(list(plugins.keys()))
```

Next step: [Review resilience and observability](resilience.md).
