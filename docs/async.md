# Async support

Py MoMo API provides complete asynchronous support through the `AsyncPyMomoAPI` class, backed by the `httpx.AsyncClient` package. This allows you to integrate payment features into async web frameworks (such as FastAPI, Starlette, or Sanic) without blocking the main event loop.

## Parity with synchronous client

The async client exposes the exact same properties, method signatures, request models, and response results as the synchronous client. All remote network calls are declared as coroutines (`async def`) and must be awaited.


## Usage example

Initialize the async client using the standard `AsyncPyMomoAPI` context manager:

```python
import asyncio
from py_momo_api import AsyncPyMomoAPI, PyMomoAPIConfig, ProductConfig

config = PyMomoAPIConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)

async def main():
    async with AsyncPyMomoAPI(config) as client:
        # Check account balance asynchronously
        balance = await client.collection.get_balance()
        print(f"Balance: {balance.available_balance} {balance.currency}")

        # Initiate a payment request asynchronously
        reference_id = await client.collection.request_to_pay(
            amount="10.00",
            currency="EUR",
            payer_msisdn="256771234567",
            external_id="invoice-async-1",
        )
        print(f"Reference ID: {reference_id}")

# Run the async main function
asyncio.run(main())
```

## Running requests concurrently

Because the client methods are non-blocking coroutines, you can run multiple MoMo API calls concurrently using `asyncio.gather`:

```python
async def check_multiple_balances(config_coll, config_disb):
    # Two clients sharing a single loop run
    async with AsyncPyMomoAPI(config_coll) as client_c, AsyncPyMomoAPI(config_disb) as client_d:
        balances = await asyncio.gather(
            client_c.collection.get_balance(),
            client_d.disbursement.get_balance()
        )
        print(f"Collection Balance: {balances[0].available_balance}")
        print(f"Disbursement Balance: {balances[1].available_balance}")
```
