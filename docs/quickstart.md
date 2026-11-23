# Quickstart

This guide walks through installing `py-momo-sdk`, provisioning sandbox credentials, submitting a payment request, and polling for settlement.

## Installation

Install the core library from PyPI:

```bash
pip install py-momo-sdk
```

Install optional extras when you need the CLI, Airtel RSA PIN encryption, or web framework integrations:

```bash
pip install "py-momo-sdk[cli]"      # Typer CLI tool
pip install "py-momo-sdk[airtel]"   # cryptography for encrypt_airtel_pin()
pip install "py-momo-sdk[fastapi]"  # FastAPI and Starlette ASGI webhook verifier
pip install "py-momo-sdk[django]"   # Django webhook verifier
pip install "py-momo-sdk[all]"      # All optional extras
```

Inspect the installed library version programmatically via `py_momo_sdk.__version__`:

```python
import py_momo_sdk

print(py_momo_sdk.__version__)
```

## Setting up sandbox credentials

Create a sandbox account on the MTN MoMo developer portal to obtain a subscription key, then provision an API user and API key:

```python
from py_momo_sdk import PyMomoSDK, PyMomoSDKConfig

config = PyMomoSDKConfig(environment="sandbox")

with PyMomoSDK(config) as client:
    provisioner = client.create_sandbox_provisioner("your-subscription-key")
    credentials = provisioner.provision(callback_host="https://example.com")
    print(f"API user UUID: {credentials['api_user']}")
    print(f"API key: {credentials['api_key']}")
```

## Making a collection request to pay

Configure `PyMomoSDKConfig` with your credentials and request a payment from a mobile subscriber:

```python
from py_momo_sdk import ProductConfig, PyMomoSDK, PyMomoSDKConfig
from py_momo_sdk.exceptions import PyMomoSDKError

config = PyMomoSDKConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)

with PyMomoSDK(config) as client:
    try:
        reference_id = client.collection.request_to_pay(
            amount="100.00",
            currency="EUR",
            payer_msisdn="256772123456",
            external_id="12345678",
            payer_message="Payment for utilities",
            payee_note="June invoice",
        )
        print(f"Payment initiated. Reference ID: {reference_id}")
    except PyMomoSDKError as e:
        print(f"Failed to initiate payment: {e}")
```

## Polling for transaction settlement

Transactions on mobile money networks settle asynchronously. Use `wait_for_settlement()` (or `async_wait_for_settlement()` in async services) to poll with bounded exponential backoff and jitter until the transaction leaves the pending state:

```python
from py_momo_sdk import (
    PyMomoSDK,
    TransactionFailedError,
    wait_for_settlement,
)

with PyMomoSDK(config) as client:
    reference_id = "550e8400-e29b-41d4-a716-446655440000"

    try:
        result = wait_for_settlement(
            lambda: client.collection.get_payment_status(reference_id),
            timeout=60.0,
            interval=2.0,
            backoff=1.5,
            raise_on_failed=True,
        )
        print(f"Settled: {result.status} (ID: {result.financial_transaction_id})")
    except TransactionFailedError as e:
        print(f"Transaction {e.reference_id} failed: {e.reason}")
```

## Handling errors

All library exceptions inherit from `PyMomoSDKError`. Handle specific failure states explicitly:

```python
from py_momo_sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    PyMomoSDKError,
)

try:
    with PyMomoSDK(config) as client:
        client.collection.get_balance()
except AuthenticationError:
    print("Authentication failed. Verify your credentials and keys.")
except BadRequestError as e:
    print(f"Bad request: {e}. API details: {e.response_body}")
except PyMomoSDKError as e:
    print(f"Library error occurred: {e}")
```

Next step: [Review authentication options](authentication.md).
