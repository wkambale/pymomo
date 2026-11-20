# PyMoMo (`py-momo-api`)

[![PyPI Version](https://img.shields.io/pypi/v/py-momo-api.svg)](https://pypi.org/project/py-momo-api/)
[![Build Status](https://github.com/wkambale/pymomo/actions/workflows/ci.yml/badge.svg)](https://github.com/wkambale/pymomo/actions)
[![License](https://img.shields.io/github/license/wkambale/pymomo.svg)](https://github.com/wkambale/pymomo/blob/main/LICENSE)

PyMoMo (`py-momo-api` 1.0.3) is a fully-typed, production-grade Python client library for the MTN Mobile Money (MoMo) Open API and Airtel Money API. It provides synchronous and asynchronous clients with complete feature parity, automatic token caching, strict validation, and comprehensive product coverage.

Developed for high reliability and clean developer experience, PyMoMo adheres to the strict security standards of modern payment systems.

- **PyPI Package:** [py-momo-api](https://pypi.org/project/py-momo-api/) (`1.0.3`, imported as `pymomo`)
- **Authoritative Docs:** [https://pymomo.aiforuganda.org](https://pymomo.aiforuganda.org)
- **Repository:** [https://github.com/wkambale/pymomo](https://github.com/wkambale/pymomo)

## Features

- **Sync & Async Parity:** Backed by `httpx.Client` and `httpx.AsyncClient` with matching interfaces.
- **Pydantic v2 Models:** Fully typed request/response validation and serialization.
- **Automated Token Caching:** Thread-safe and async-safe in-memory token management with automated cache invalidation and retry-once logic.
- **Comprehensive API Coverage:** Full MTN MoMo Collection (including CIBA/OAuth2 token exchange), Disbursement, Remittance, Sandbox, and Airtel Money APIs.
- **Robust Security:** Strict HTTPS and input validation, constant-time webhook HMAC and source IP verification, and secret-redacting exceptions and representations.
- **CLI Utility:** Ships with a Typer-powered CLI to bootstrap sandbox credentials, initiate payments, and query balances or transaction status.

## Installation

Install `py-momo-api` (1.0.3) from PyPI using pip:

```bash
pip install py-momo-api
```

For development dependencies, install with:

```bash
pip install -e ".[dev]"
```

## Quickstart

### 1. Sandbox Provisioning

To get started with the sandbox environment, bootstrap a new API User and API Key:

```python
from pymomo import MomoClient, MomoConfig

config = MomoConfig(environment="sandbox")

with MomoClient(config) as client:
    provisioner = client.create_sandbox_provisioner("your-sandbox-subscription-key")
    credentials = provisioner.provision(callback_host="https://pymomo.aiforuganda.org")

    print(f"API User: {credentials['api_user']}")
    print(f"API Key: {credentials['api_key']}")
```

### 2. Collection (Synchronous Example)

Make a payment request (Request to Pay) using the synchronous client:

```python
from pymomo import MomoClient, MomoConfig, ProductConfig

config = MomoConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-collection-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
        callback_url="https://pymomo.aiforuganda.org/webhook",
    ),
)

with MomoClient(config) as client:
    # Query account balance
    balance = client.collection.get_balance()
    print(f"Available Balance: {balance.available_balance} {balance.currency}")

    # Initiate a Request to Pay
    reference_id = client.collection.request_to_pay(
        amount="1000.00",
        currency="UGX",
        payer_msisdn="256771234567",
        external_id="ext-tx-12345",
        payer_message="Payment for Invoice #123",
        payee_note="Thank you for shopping with us",
    )
    print(f"Transaction Reference: {reference_id}")

    # Check status
    tx = client.collection.get_payment_status(reference_id)
    print(f"Transaction Status: {tx.status}")
```

### 3. Disbursement (Asynchronous Example)

Send funds using the asynchronous client:

```python
import asyncio
from pymomo import AsyncMomoClient, MomoConfig, ProductConfig

config = MomoConfig(
    environment="sandbox",
    disbursement=ProductConfig(
        subscription_key="your-disbursement-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)

async def main():
    async with AsyncMomoClient(config) as client:
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
            payee_note="Disbursement Successful",
        )

        # Query transaction details
        status = await client.disbursement.get_transfer_status(reference_id)
        print(f"Transfer status: {status.status} (ID: {status.financial_transaction_id})")

asyncio.run(main())
```

## CLI Usage

PyMoMo bundles a CLI tool for common sandbox management operations:

```bash
# Show installed version
pymomo --version

# Provision a sandbox environment
pymomo sandbox provision --subscription-key "your-key"

# Query the collection balance
pymomo collection balance --subscription-key "your-key" --api-user "550e8400-e29b-41d4-a716-446655440000" --api-key "key"

# Check the status of a Request to Pay transaction
pymomo collection status "550e8400-e29b-41d4-a716-446655440000" --subscription-key "your-key" --api-user "550e8400-e29b-41d4-a716-446655440000" --api-key "key"
```

Use `pymomo --help` to list all available commands and flags.

## Testing

Run tests and produce coverage reports:

```bash
# Style check and format check
ruff check .
black --check .
isort --check .

# Static type check
mypy pymomo/

# Security analysis
bandit -r pymomo/

# Test execution with coverage
pytest --cov=pymomo --cov-report=term-missing
```

## License

Apache License 2.0. See [LICENSE](LICENSE) for more details.
