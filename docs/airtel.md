# Airtel Money

Py MoMo SDK includes a synchronous client for the Airtel Money Open API covering collections, disbursements, and merchant wallet balances.

## Initializing the Airtel client

Configure `AirtelConfig` with your Airtel developer credentials, ISO 3166-1 alpha-2 country code, and ISO 4217 currency code. Supply `pin` when executing disbursement payouts.

```python
from py_momo_sdk import AirtelClient, AirtelConfig

config = AirtelConfig(
    client_id="your-airtel-client-id",
    client_secret="your-airtel-client-secret",
    country="UG",
    currency="UGX",
    pin="your-encrypted-pin",  # Required for disbursements
    environment="sandbox",     # Or "production"
)

with AirtelClient(config) as client:
    balance = client.disbursement.get_balance()
    print(f"Balance: {balance.data.wallet.balance} {balance.data.wallet.currency}")
```

## Collection

### Request to pay

Initiate a USSD Push payment collection from an Airtel Money subscriber. If `reference_id` is omitted, Py MoMo SDK generates a canonical UUID v4 automatically.

```python
with AirtelClient(config) as client:
    reference_id = client.collection.request_to_pay(
        amount="1000.00",
        payer_msisdn="256751234567",
        # Optional canonical UUID v4; omit to auto-generate
        reference_id="550e8400-e29b-41d4-a716-446655440000",
    )
    print(f"Collection reference: {reference_id}")
```

### Get payment status

Poll the status of a collection transaction using its reference ID. Always inspect the helper methods (`is_successful()`, `is_pending()`, `is_failed()`), which evaluate the authoritative `data.transaction.status` field rather than the outer API envelope code.

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

Send a disbursement payout to a subscriber. Requires `pin` to be configured on `AirtelConfig`.

```python
with AirtelClient(config) as client:
    reference_id = client.disbursement.transfer(
        amount="5000.00",
        payee_msisdn="256751234567",
    )
    print(f"Disbursement reference: {reference_id}")
```

### Get transfer status

Query the final status of a disbursement transaction.

```python
with AirtelClient(config) as client:
    result = client.disbursement.get_transfer_status(reference_id)
    print(f"Status: {result.data.transaction.status}")
    print(f"Successful: {result.is_successful()}")
```

### Get wallet balance

Query the merchant wallet balance.

```python
with AirtelClient(config) as client:
    balance = client.disbursement.get_balance()
    wallet = balance.data.wallet
    print(f"Available: {wallet.balance} {wallet.currency} ({wallet.status})")
```

## Security notes

- `AirtelConfig`, `AirtelDisbursementRequest`, and internal token caches redact `client_secret`, `pin`, and bearer access tokens from string and debug representations.
- All requests enforce HTTPS base URLs and disable automatic HTTP redirects to prevent credential leakage.
- OAuth2 access tokens are cached in memory with thread-safe refresh locking and automatic retry-once handling on HTTP 401 responses.

Next step: [Review webhook security](webhooks.md).
