3

# Py MoMo SDK

[![PyPI version](https://img.shields.io/pypi/v/py-momo-sdk.svg)](https://pypi.org/project/py-momo-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/py-momo-sdk.svg)](https://pypi.org/project/py-momo-sdk/)
[![Build status](https://github.com/wkambale/pymomo/actions/workflows/ci.yml/badge.svg)](https://github.com/wkambale/pymomo/actions)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Py MoMo SDK (`py-momo-sdk` 1.1.0) is a strictly typed, production-grade Python client library for the MTN Mobile Money (MoMo) Open API and Airtel Money API. It provides synchronous and asynchronous clients with matching interfaces, automatic token caching, strict validation, and complete product coverage.
Py MoMo SDK (`py-momo-sdk` 1.1.0) is a strictly typed Python client library for the MTN Mobile Money (MoMo) Open API and Airtel Money API. It provides synchronous and asynchronous clients with matching interfaces, automatic token caching, strict validation, and complete product coverage.

Developed for high reliability and clean developer experience, Py MoMo SDK adheres to the strict security standards of modern payment systems.

- **PyPI package:** [py-momo-sdk](https://pypi.org/project/py-momo-sdk/) (`1.1.0`, imported as `py_momo_sdk`)
- **Python support:** Python 3.10 to 3.15
- **Documentation:** [https://wkambale.github.io/pymomo/](https://wkambale.github.io/pymomo/)
- **Repository:** [https://github.com/wkambale/pymomo](https://github.com/wkambale/pymomo)

## Features

- **Sync and async parity:** `PyMomoSDK` and `AsyncPyMomoSDK` backed by `httpx.Client` and `httpx.AsyncClient` with matching interfaces.
- **Pydantic v2 models:** Fully typed request and response validation and serialization.
- **Automated token caching:** Thread-safe and async-safe in-memory token management with automatic cache invalidation and retry-once logic.
- **Comprehensive API coverage:** Full MTN MoMo Collection (including CIBA and OAuth2 token exchange), Disbursement, Remittance, Sandbox, synchronous and asynchronous Airtel Money (`AirtelClient` and `AsyncAirtelClient`), Wave, M-Pesa (Daraja), Paystack, Flutterwave, and Orange Money adapters behind `PaymentRouter`.
- **Resilience and observability:** Configurable idempotent retries with `Retry-After` and jitter, settlement polling helpers, `TelemetryHook` observability events, MSISDN carrier auto-routing, FastAPI and Django webhook verifiers, and a local `py-momo-sdk mock` simulator.
- **CLI utility:** Ships with the `py-momo-sdk` Typer-powered CLI to bootstrap sandbox credentials, initiate payments, and query balances or transaction status.

## Installation

Install `py-momo-sdk` (1.1.0) from PyPI using pip:

```bash
pip install py-momo-sdk
```

For development dependencies, install with:

```bash
pip install -e ".[dev]"
```

## Quickstart

### Sandbox provisioning

Bootstrap a new sandbox API user and API key:

```python
from py_momo_sdk import PyMomoSDK, PyMomoSDKConfig

config = PyMomoSDKConfig(environment="sandbox")

with PyMomoSDK(config) as client:
    provisioner = client.create_sandbox_provisioner("your-sandbox-subscription-key")
    credentials = provisioner.provision(callback_host="https://example.com")

    print(f"API user: {credentials['api_user']}")
    print(f"API key: {credentials['api_key']}")
```

### Collection (synchronous example)

Request a payment from a subscriber using the synchronous client:

```python
from py_momo_sdk import ProductConfig, PyMomoSDK, PyMomoSDKConfig

config = PyMomoSDKConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-collection-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
        callback_url="https://example.com/webhook",
    ),
)

with PyMomoSDK(config) as client:
    # Query account balance
    balance = client.collection.get_balance()
    print(f"Available balance: {balance.available_balance} {balance.currency}")

    # Initiate a request to pay
    reference_id = client.collection.request_to_pay(
        amount="1000.00",
        currency="UGX",
        payer_msisdn="256771234567",
        external_id="ext-tx-12345",
        payer_message="Payment for invoice 123",
        payee_note="Thank you for shopping with us",
    )
    print(f"Transaction reference: {reference_id}")

    # Check status
    tx = client.collection.get_payment_status(reference_id)
    print(f"Transaction status: {tx.status}")
```

### Disbursement (asynchronous example)

Send funds using the asynchronous client:

```python
import asyncio
from py_momo_sdk import AsyncPyMomoSDK, ProductConfig, PyMomoSDKConfig

config = PyMomoSDKConfig(
    environment="sandbox",
    disbursement=ProductConfig(
        subscription_key="your-disbursement-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)

async def main() -> None:
    async with AsyncPyMomoSDK(config) as client:
        # Check active status of a mobile money user
        is_active = await client.disbursement.is_account_holder_active("256771234567")
        print(f"Account holder active: {is_active}")

        # Initiate a transfer
        reference_id = await client.disbursement.transfer(
            amount="5000.00",
            currency="UGX",
            payee_msisdn="256771234567",
            external_id="disb-tx-9999",
            payer_message="Staff salary payment",
            payee_note="Disbursement successful",
        )

        # Query transaction details
        status = await client.disbursement.get_transfer_status(reference_id)
        print(f"Transfer status: {status.status} (ID: {status.financial_transaction_id})")

asyncio.run(main())
```

## CLI usage

Py MoMo SDK bundles the `py-momo-sdk` CLI tool for sandbox management, balance checks, and payment queries:

```bash
# Show installed version
py-momo-sdk --version

# Provision a sandbox environment
py-momo-sdk sandbox provision --subscription-key "your-key"

# Query the collection balance
py-momo-sdk collection balance --subscription-key "your-key" --api-user "550e8400-e29b-41d4-a716-446655440000" --api-key "key"

# Check the status of a request to pay transaction
py-momo-sdk collection status "550e8400-e29b-41d4-a716-446655440000" --subscription-key "your-key" --api-user "550e8400-e29b-41d4-a716-446655440000" --api-key "key"
```

Use `py-momo-sdk --help` to list all available commands and flags.

## Testing

Run checks, security analysis, and coverage reports:

```bash
# Style and format checks
ruff check .
black --check .
isort --check .

# Static type check
mypy py_momo_sdk/

# Security analysis
bandit -r py_momo_sdk/

# Test execution with coverage
pytest --cov=py_momo_sdk --cov-report=term-missing
```

## License

MIT License. Copyright (c) 2026 Wesley Kambale. See [LICENSE](LICENSE) for more details.
