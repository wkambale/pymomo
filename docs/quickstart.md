# Quickstart

This guide provides a walk-through to get started with Py MoMo API, from installing the package to initiating and checking transactions in the sandbox.

## Installation

Install the package via pip:

```bash
pip install py-momo-api
```

## Setting up sandbox credentials

Before writing code, you need to create a sandbox account on the MTN MoMo developer portal to obtain a subscription key. With that subscription key, you can provision an API user and API key:

```python
from py_momo_api import PyMomoAPI, PyMomoAPIConfig

config = PyMomoAPIConfig(environment="sandbox")

with PyMomoAPI(config) as client:
    # Use the sandbox provisioner to bootstrap a sandbox API user and key
    provisioner = client.create_sandbox_provisioner("your-subscription-key")
    credentials = provisioner.provision(callback_host="https://pymomo.aiforuganda.org")
    print(f"API User UUID: {credentials['api_user']}")
    print(f"API Key: {credentials['api_key']}")
```

## Making a collection request to pay

Once you have your credentials, you can configure the client and request a payment from a mobile subscriber:

```python
import time
from py_momo_api import PyMomoAPI, PyMomoAPIConfig, ProductConfig
from py_momo_api.exceptions import PyMomoAPIError

config = PyMomoAPIConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)

with PyMomoAPI(config) as client:
    try:
        # Initiate payment
        reference_id = client.collection.request_to_pay(
            amount="100.00",
            currency="EUR",
            payer_msisdn="256772123456",
            external_id="12345678",
            payer_message="Payment for utilities",
            payee_note="June invoice",
        )
        print(f"Payment initiated. Reference ID: {reference_id}")
    except PyMomoAPIError as e:
        print(f"Failed to initiate payment: {e}")
```

## Polling for the transaction status

Transactions on the MTN MoMo network are processed asynchronously. When you submit a write request, you get a `reference_id` back, which you must poll to obtain the final outcome:

```python
with PyMomoAPI(config) as client:
    reference_id = "550e8400-e29b-41d4-a716-446655440000"

    # Simple polling loop to check status
    for _ in range(10):
        try:
            result = client.collection.get_payment_status(reference_id)
            print(f"Status: {result.status}")

            if result.is_successful():
                print(f"Transaction completed. Tx ID: {result.financial_transaction_id}")
                break
            elif result.is_failed():
                print(f"Transaction failed. Reason: {result.reason}")
                break
        except PyMomoAPIError as e:
            print(f"Status check failed: {e}")

        time.sleep(3)
```

## Handling errors

All exceptions thrown by the package inherit from `PyMomoAPIError`. You can write targeted exception handlers to handle specific states, such as a bad request or expired credentials:

```python
from py_momo_api.exceptions import (
    AuthenticationError,
    BadRequestError,
    PyMomoAPIError,
)

try:
    with PyMomoAPI(config) as client:
        client.collection.get_balance()
except AuthenticationError:
    print("Authentication failed. Please verify your credentials and keys.")
except BadRequestError as e:
    print(f"Bad request: {e}. API details: {e.response_body}")
except PyMomoAPIError as e:
    print(f"General library error occurred: {e}")
```
