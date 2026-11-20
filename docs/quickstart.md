---
hide:
  - navigation
---

# Quickstart

This guide walks through installing `py-momo-sdk`, provisioning sandbox credentials, submitting a payment request, and polling for completion.

## Installation

Install the package via pip:

```bash
pip install py-momo-sdk
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
import time
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

## Polling for the transaction status

Transactions on the MTN MoMo network are processed asynchronously. Poll the returned `reference_id` to obtain the final settlement outcome:

```python
with PyMomoSDK(config) as client:
    reference_id = "550e8400-e29b-41d4-a716-446655440000"

    for _ in range(10):
        try:
            result = client.collection.get_payment_status(reference_id)
            print(f"Status: {result.status}")

            if result.is_successful():
                print(f"Transaction completed. Transaction ID: {result.financial_transaction_id}")
                break
            elif result.is_failed():
                print(f"Transaction failed. Reason: {result.reason}")
                break
        except PyMomoSDKError as e:
            print(f"Status check failed: {e}")

        time.sleep(3)
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
