# Async support

Py MoMo SDK provides full asynchronous parity across every client and router in the library, backed by `httpx.AsyncClient` with per-event-loop token-refresh locks so concurrent coroutines never trigger redundant OAuth token requests.

## Asynchronous client catalog

| Synchronous class | Asynchronous class |
| --- | --- |
| `PyMomoSDK` | `AsyncPyMomoSDK` |
| `AirtelClient` | `AsyncAirtelClient` |
| `WaveClient` | `AsyncWaveClient` |
| `MpesaClient` | `AsyncMpesaClient` |
| `PaystackClient` | `AsyncPaystackClient` |
| `FlutterwaveClient` | `AsyncFlutterwaveClient` |
| `OrangeMoneyClient` | `AsyncOrangeMoneyClient` |
| `PaymentRouter` | `AsyncPaymentRouter` |
| `wait_for_settlement()` | `async_wait_for_settlement()` |

## MTN MoMo async example

Initialize `AsyncPyMomoSDK` using `async with` and await settlement via `async_wait_for_settlement()`:

```python
import asyncio
from py_momo_sdk import (
    AsyncPyMomoSDK,
    ProductConfig,
    PyMomoSDKConfig,
    async_wait_for_settlement,
)

config = PyMomoSDKConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)


async def main() -> None:
    async with AsyncPyMomoSDK(config) as client:
        balance = await client.collection.get_balance()
        print(f"Balance: {balance.available_balance} {balance.currency}")

        reference_id = await client.collection.request_to_pay(
            amount="10.00",
            currency="EUR",
            payer_msisdn="256771234567",
            external_id="invoice-async-1",
        )
        settled = await async_wait_for_settlement(
            lambda: client.collection.get_payment_status(reference_id),
            timeout=60.0,
            interval=2.0,
        )
        print(f"Reference {reference_id}: {settled.status}")


asyncio.run(main())
```

## Running requests concurrently

Because all async client methods are non-blocking coroutines, run independent balance or status calls concurrently using `asyncio.gather`:

```python
import asyncio
from py_momo_sdk import AsyncPyMomoSDK, PyMomoSDKConfig


async def check_multiple_balances(
    config_coll: PyMomoSDKConfig,
    config_disb: PyMomoSDKConfig,
) -> None:
    async with (
        AsyncPyMomoSDK(config_coll) as client_c,
        AsyncPyMomoSDK(config_disb) as client_d,
    ):
        coll_bal, disb_bal = await asyncio.gather(
            client_c.collection.get_balance(),
            client_d.disbursement.get_balance(),
        )
        print(f"Collection balance: {coll_bal.available_balance}")
        print(f"Disbursement balance: {disb_bal.available_balance}")
```

## Multi-provider async routing

Combine `AsyncMtnMomoProvider`, `AsyncAirtelMoneyProvider`, `AsyncWaveProvider`, `AsyncMpesaProvider`, `AsyncPaystackProvider`, `AsyncFlutterwaveProvider`, and `AsyncOrangeMoneyProvider` inside `AsyncPaymentRouter`:

```python
import asyncio
from py_momo_sdk import (
    AirtelConfig,
    AsyncAirtelClient,
    AsyncAirtelMoneyProvider,
    AsyncMtnMomoProvider,
    AsyncPaymentRouter,
    AsyncPyMomoSDK,
    PaymentRequest,
    ProductConfig,
    PyMomoSDKConfig,
)


async def route_async() -> None:
    mtn_sdk = AsyncPyMomoSDK(
        PyMomoSDKConfig(
            environment="sandbox",
            collection=ProductConfig(
                subscription_key="your-mtn-key",
                api_user="550e8400-e29b-41d4-a716-446655440000",
                api_key="your-mtn-secret",
            ),
        )
    )
    airtel_sdk = AsyncAirtelClient(
        AirtelConfig(
            client_id="your-airtel-id",
            client_secret="your-airtel-secret",
            country="UG",
            currency="UGX",
        )
    )

    async with AsyncPaymentRouter(
        [AsyncMtnMomoProvider(mtn_sdk), AsyncAirtelMoneyProvider(airtel_sdk)]
    ) as router:
        res = await router.collect(
            PaymentRequest(
                amount="2500",
                currency="UGX",
                payer_msisdn="256751234567",
                external_id="async-order-1",
            )
        )
        print(res.provider, res.reference_id, res.status)


asyncio.run(route_async())
```

Next step: [Review error handling](error-handling.md).
