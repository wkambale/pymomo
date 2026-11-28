<div align="center">
  <h1>Py MoMo SDK</h1>
  <p><b>Strictly typed Python SDK for MTN Mobile Money, Airtel Money, Wave, Safaricom M-Pesa, Paystack, Flutterwave, and Orange Money</b></p>

  [![PyPI version](https://img.shields.io/pypi/v/py-momo-sdk.svg)](https://pypi.org/project/py-momo-sdk/)
  [![Python versions](https://img.shields.io/pypi/pyversions/py-momo-sdk.svg)](https://pypi.org/project/py-momo-sdk/)
  [![Build status](https://github.com/wkambale/pymomo/actions/workflows/ci.yml/badge.svg)](https://github.com/wkambale/pymomo/actions)
  [![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
</div>

Py MoMo SDK (`py-momo-sdk` 1.3.3) is a strictly typed Python client library for MTN Mobile Money (MoMo), Airtel Money, Wave, Safaricom M-Pesa (Daraja), Paystack, Flutterwave, and Orange Money behind a unified `PaymentRouter`. It provides synchronous and asynchronous clients with matching interfaces, automatic token caching, strict input validation, and verified webhook security.

- **PyPI package:** [py-momo-sdk](https://pypi.org/project/py-momo-sdk/) (`1.3.3`, imported as `py_momo_sdk`, inspectable via `py_momo_sdk.__version__`)
- **Python support:** Python 3.10 to 3.15
- **Documentation:** [https://wkambale.github.io/pymomo/](https://wkambale.github.io/pymomo/)
- **Repository:** [https://github.com/wkambale/pymomo](https://github.com/wkambale/pymomo)

## Features

- **Sync and async parity:** `PyMomoSDK`, `AsyncPyMomoSDK`, `AirtelClient`, `AsyncAirtelClient`, `PaymentRouter`, `AsyncPaymentRouter`, and all provider clients backed by `httpx.Client` and `httpx.AsyncClient`.
- **Pydantic v2 models:** Fully typed request and response validation and serialization.
- **Automated token caching:** Thread-safe and async-safe double-checked token management with conditional `expected_token` invalidation and retry-once logic.
- **Comprehensive African payment coverage:** MTN MoMo Collection (including CIBA and OAuth2 token exchange/refresh), Disbursement, Remittance, and Sandbox; Airtel Money (`AirtelClient` / `AsyncAirtelClient` with `encrypt_airtel_pin()`); Wave; Safaricom M-Pesa (Daraja); Paystack; Flutterwave; and Orange Money behind `PaymentRouter`.
- **Resilience and observability:** Configurable idempotent retries with `Retry-After` and jitter, bounded streaming response caps (`max_response_bytes`), HTTP `3xx` redirect rejection, `wait_for_settlement()` / `async_wait_for_settlement()`, `TelemetryHook` observability events, 18-market MSISDN carrier detection, FastAPI/Starlette and Django webhook verifiers, and a local `py-momo-sdk mock` simulator.
- **CLI utility:** Optional `py-momo-sdk` Typer CLI for sandbox provisioning, collections, disbursements, remittances, Airtel PIN encryption, webhook verification, carrier lookup, and mock server hosting.

## Installation

Install the core library from PyPI:

```bash
pip install py-momo-sdk
```

Install optional extras as needed:

```bash
pip install "py-momo-sdk[cli]"      # Typer CLI tool
pip install "py-momo-sdk[airtel]"   # cryptography for encrypt_airtel_pin()
pip install "py-momo-sdk[fastapi]"  # FastAPI / Starlette ASGI webhook verifier
pip install "py-momo-sdk[django]"   # Django webhook verifier
pip install "py-momo-sdk[all]"      # All optional extras
```

For local development and testing:

```bash
pip install -e ".[all,dev]"
```

## Quickstart

### Check installed version and provision sandbox credentials

```python
import py_momo_sdk
from py_momo_sdk import PyMomoSDK, PyMomoSDKConfig

print(py_momo_sdk.__version__)

config = PyMomoSDKConfig(environment="sandbox")

with PyMomoSDK(config) as client:
    provisioner = client.create_sandbox_provisioner("your-sandbox-subscription-key")
    credentials = provisioner.provision(callback_host="https://example.com")

    print(f"API user: {credentials['api_user']}")
    print(f"API key: {credentials['api_key']}")
```

### Collection (synchronous example)

Request a payment from a subscriber and wait for settlement:

```python
from py_momo_sdk import (
    ProductConfig,
    PyMomoSDK,
    PyMomoSDKConfig,
    wait_for_settlement,
)

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
    balance = client.collection.get_balance()
    print(f"Available balance: {balance.available_balance} {balance.currency}")

    reference_id = client.collection.request_to_pay(
        amount="1000",
        currency="UGX",
        payer_msisdn="256771234567",
        external_id="ext-tx-12345",
        payer_message="Payment for invoice 123",
        payee_note="Thank you for shopping with us",
    )

    tx = wait_for_settlement(
        lambda: client.collection.get_payment_status(reference_id),
        timeout=60.0,
        interval=2.0,
    )
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
        is_active = await client.disbursement.is_account_holder_active("256771234567")
        print(f"Account holder active: {is_active}")

        reference_id = await client.disbursement.transfer(
            amount="5000",
            currency="UGX",
            payee_msisdn="256771234567",
            external_id="disb-tx-9999",
            payer_message="Staff salary payment",
            payee_note="Disbursement successful",
        )

        status = await client.disbursement.get_transfer_status(reference_id)
        print(f"Transfer status: {status.status} (ID: {status.financial_transaction_id})")


asyncio.run(main())
```

## CLI usage

Install `pip install "py-momo-sdk[cli]"` and export credentials via `PY_MOMO_SDK_*` environment variables or `--*-file` flags so secrets are never recorded in shell history or process listings:

```bash
export PY_MOMO_SDK_ENVIRONMENT="sandbox"
export PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY="your-key"
export PY_MOMO_SDK_COLLECTION_API_USER="550e8400-e29b-41d4-a716-446655440000"
export PY_MOMO_SDK_COLLECTION_API_KEY="your-api-key"

py-momo-sdk --version
py-momo-sdk sandbox provision --callback-host "example.com" --output-file ./creds.json
py-momo-sdk collection balance
py-momo-sdk collection status "550e8400-e29b-41d4-a716-446655440000"
```

Use `py-momo-sdk --help` to list all available commands and options.

## Testing

Run style checks, type checking, security analysis, and coverage reports:

```bash
ruff check .
black --check .
isort --check-only .
mypy py_momo_sdk/ tests/
bandit -r py_momo_sdk/ -ll
pytest --cov=py_momo_sdk --cov-report=term-missing
```

## License

MIT License. Copyright (c) 2026 Wesley Kambale. See [LICENSE](LICENSE) for more details.
