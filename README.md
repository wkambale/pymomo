# Py MoMo API (`py-momo-api`)

[![PyPI version](https://img.shields.io/pypi/v/py-momo-api.svg)](https://pypi.org/project/py-momo-api/)
[![Build status](https://github.com/wkambale/pymomo/actions/workflows/ci.yml/badge.svg)](https://github.com/wkambale/pymomo/actions)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Py MoMo API (`py-momo-api` 1.0.5) is a strictly typed, production-grade Python client library for the MTN Mobile Money (MoMo) Open API and Airtel Money API. It provides synchronous and asynchronous clients with matching interfaces, automatic token caching, strict validation, and complete product coverage.

Developed for high reliability and clean developer experience, Py MoMo API adheres to the strict security standards of modern payment systems.

- **PyPI package:** [py-momo-api](https://pypi.org/project/py-momo-api/) (`1.0.5`, imported as `py_momo_api`)
- **Documentation:** [https://pymomo.aiforuganda.org](https://pymomo.aiforuganda.org)
- **Repository:** [https://github.com/wkambale/pymomo](https://github.com/wkambale/pymomo)

## Features

- **Sync and async parity:** `PyMomoAPI` and `AsyncPyMomoAPI` backed by `httpx.Client` and `httpx.AsyncClient` with matching interfaces.
- **Pydantic v2 models:** Fully typed request and response validation and serialization.
- **Automated token caching:** Thread-safe and async-safe in-memory token management with automatic cache invalidation and retry-once logic.
- **Comprehensive API coverage:** Full MTN MoMo Collection (including CIBA and OAuth2 token exchange), Disbursement, Remittance, Sandbox, and Airtel Money APIs.
- **Robust security:** Strict HTTPS and input validation, constant-time webhook HMAC and source IP verification, and secret-redacting exceptions and representations.
- **CLI utility:** Ships with the `py-momo-api` Typer-powered CLI to bootstrap sandbox credentials, initiate payments, and query balances or transaction status.

## Installation

Install `py-momo-api` (1.0.5) from PyPI using pip:

```bash
pip install py-momo-api
```

For development dependencies, install with:

```bash
pip install -e ".[dev]"
```

## Quickstart

### Sandbox provisioning

Bootstrap a new sandbox API user and API key:

```python
from py_momo_api import PyMomoAPI, PyMomoAPIConfig

config = PyMomoAPIConfig(environment="sandbox")

with PyMomoAPI(config) as client:
    provisioner = client.create_sandbox_provisioner("your-sandbox-subscription-key")
    credentials = provisioner.provision(callback_host="https://pymomo.aiforuganda.org")

    print(f"API user: {credentials['api_user']}")
    print(f"API key: {credentials['api_key']}")
```

### Collection (synchronous example)

Request a payment from a subscriber using the synchronous client:

```python
from py_momo_api import ProductConfig, PyMomoAPI, PyMomoAPIConfig

config = PyMomoAPIConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-collection-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
        callback_url="https://pymomo.aiforuganda.org/webhook",
    ),
)

with PyMomoAPI(config) as client:
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
from py_momo_api import AsyncPyMomoAPI, ProductConfig, PyMomoAPIConfig

config = PyMomoAPIConfig(
    environment="sandbox",
    disbursement=ProductConfig(
        subscription_key="your-disbursement-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)

async def main() -> None:
    async with AsyncPyMomoAPI(config) as client:
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

Py MoMo API bundles the `py-momo-api` CLI tool for sandbox management, balance checks, and payment queries:

```bash
# Show installed version
py-momo-api --version

# Provision a sandbox environment
py-momo-api sandbox provision --subscription-key "your-key"

# Query the collection balance
py-momo-api collection balance --subscription-key "your-key" --api-user "550e8400-e29b-41d4-a716-446655440000" --api-key "key"

# Check the status of a request to pay transaction
py-momo-api collection status "550e8400-e29b-41d4-a716-446655440000" --subscription-key "your-key" --api-user "550e8400-e29b-41d4-a716-446655440000" --api-key "key"
```

Use `py-momo-api --help` to list all available commands and flags.

## Testing

Run checks, security analysis, and coverage reports:

```bash
# Style and format checks
ruff check .
black --check .
isort --check .

# Static type check
mypy py_momo_api/

# Security analysis
bandit -r py_momo_api/

# Test execution with coverage
pytest --cov=py_momo_api --cov-report=term-missing
```

## License

MIT License. Copyright (c) 2026 Wesley Kambale. See [LICENSE](LICENSE) for more details.
