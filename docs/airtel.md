# Airtel Money

Py MoMo SDK includes synchronous (`AirtelClient`) and asynchronous (`AsyncAirtelClient`) clients for the Airtel Money Open API covering collections, disbursements, and merchant wallet balances.

## Initializing the Airtel client

Configure `AirtelConfig` with your Airtel developer credentials, ISO 3166-1 alpha-2 country code, and ISO 4217 currency code. Both `AirtelClient` and `AsyncAirtelClient` share full transport parity with `PyMomoSDK`: injectable `httpx` clients (`client=`), idempotent retry controls (`max_retries`, `retry_backoff`), `telemetry` hooks, and bounded streaming reads (`max_response_bytes`, defaulting to `1 MiB`).

```python
from py_momo_sdk import AirtelClient, AirtelConfig

config = AirtelConfig(
    client_id="your-airtel-client-id",
    client_secret="your-airtel-client-secret",
    country="UG",
    currency="UGX",
    pin="your-encrypted-pin",  # Required for disbursements
    environment="sandbox",     # Or "production"
    max_retries=2,
    retry_backoff=0.5,
)

with AirtelClient(config, max_response_bytes=1_048_576) as client:
    balance = client.disbursement.get_balance()
    print(f"Balance: {balance.data.wallet.balance} {balance.data.wallet.currency}")
```

## Encrypting disbursement PINs for production

In `environment="production"`, Airtel Money requires an RSA PKCS#1 v1.5 Base64-encrypted PIN ciphertext; `AirtelConfig` rejects plaintext numeric PINs in production. Install the optional `airtel` extra (`pip install "py-momo-sdk[airtel]"`) and encrypt your PIN with Airtel's public PEM key via `encrypt_airtel_pin()`:

```python
from pathlib import Path
from py_momo_sdk import AirtelConfig, encrypt_airtel_pin

public_key_pem = Path("airtel_public_key.pem").read_text(encoding="utf-8")
encrypted_pin = encrypt_airtel_pin("1234", public_key_pem)

prod_config = AirtelConfig(
    client_id="your-airtel-client-id",
    client_secret="your-airtel-client-secret",
    country="UG",
    currency="UGX",
    environment="production",
    pin=encrypted_pin,
)
```

## Collection

### Request to pay

Initiate a USSD Push payment collection from an Airtel Money subscriber. Supply an explicit merchant reference ID (`1` to `64` characters matching `A-Za-z0-9._-`, validated by `validate_airtel_reference_id()`) or omit `reference_id` to auto-generate a UUID v4:

```python
with AirtelClient(config) as client:
    reference_id = client.collection.request_to_pay(
        amount="1000",
        payer_msisdn="256751234567",
        # Optional merchant reference ID (1-64 chars A-Za-z0-9._-) or omit for UUID v4
        reference_id="order-2026-0001",
    )
    print(f"Collection reference: {reference_id}")
```

### Get payment status

Poll the status of a collection transaction using its reference ID. Always inspect `is_successful()`, `is_pending()`, and `is_failed()`, which evaluate the authoritative `data.transaction.status` field (`TS`, `TIP`, `TA`, `TF`):

```python
with AirtelClient(config) as client:
    result = client.collection.get_payment_status(reference_id)
    if result.is_successful():
        print(f"Settled. Airtel Money ID: {result.data.transaction.airtel_money_id}")
    elif result.is_pending():
        print("Transaction is still pending.")
    elif result.is_failed():
        print(f"Transaction failed: {result.data.transaction.message}")
```

## Disbursement

### Transfer funds

Send a disbursement payout to a subscriber. Requires `pin` to be configured on `AirtelConfig`:

```python
with AirtelClient(config) as client:
    reference_id = client.disbursement.transfer(
        amount="5000",
        payee_msisdn="256751234567",
        reference_id="payout-2026-0001",
    )
    print(f"Disbursement reference: {reference_id}")
```

### Get transfer status

Query the final status of a disbursement transaction:

```python
with AirtelClient(config) as client:
    result = client.disbursement.get_transfer_status(reference_id)
    print(f"Status: {result.data.transaction.status}")
    print(f"Successful: {result.is_successful()}")
```

### Get wallet balance

Query the merchant wallet balance:

```python
with AirtelClient(config) as client:
    balance = client.disbursement.get_balance()
    wallet = balance.data.wallet
    print(f"Available: {wallet.balance} {wallet.currency} ({wallet.status})")
```

## Security notes

- `AirtelConfig`, `AirtelDisbursementRequest`, and internal token caches redact `client_secret`, `pin`, and bearer access tokens from string and debug representations.
- All requests enforce HTTPS base URLs, reject HTTP `3xx` redirects, and bound response sizes with streaming reads.
- OAuth2 access tokens are cached in memory with thread-safe and async-safe double-checked locking and conditional `401` invalidation.

## Asynchronous Airtel client

Use `AsyncAirtelClient` for full non-blocking parity in FastAPI, Starlette, or asyncio services:

```python
import asyncio
from py_momo_sdk import AirtelConfig, AsyncAirtelClient


async def main() -> None:
    config = AirtelConfig(
        client_id="your-airtel-client-id",
        client_secret="your-airtel-client-secret",
        country="UG",
        currency="UGX",
    )
    async with AsyncAirtelClient(config) as client:
        balance = await client.disbursement.get_balance()
        print(balance.data.wallet.balance)


asyncio.run(main())
```

Next step: [Explore multi-provider orchestration](providers.md).
