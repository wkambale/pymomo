# Remittance

The Remittance product executes domestic or international wallet-to-wallet transfers.

## Initializing the remittance client

Always manage `PyMomoSDK` with a `with` statement (or call `client.close()`) so HTTP connection pools are closed cleanly:

```python
from py_momo_sdk import ProductConfig, PyMomoSDK, PyMomoSDKConfig

config = PyMomoSDKConfig(
    environment="sandbox",
    remittance=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
        callback_url="https://your-app.example.com/webhooks/remittance",
    ),
)

with PyMomoSDK(config) as client:
    balance = client.remittance.get_balance()
    print(f"Balance: {balance.available_balance} {balance.currency}")
```

## Transfer

Transfer funds to a beneficiary, with optional per-request `callback_url` override:

```python
with PyMomoSDK(config) as client:
    reference_id = client.remittance.transfer(
        amount="250",
        currency="UGX",
        payee_msisdn="256771234567",
        external_id="remit-404",
        payer_message="Family support",
        payee_note="Support package",
        # Optional canonical UUID v4; omit to auto-generate
        reference_id="550e8400-e29b-41d4-a716-446655440000",
        callback_url="https://your-app.example.com/webhooks/remit-404",
    )
    print(f"Remittance reference: {reference_id}")
```

## Get transfer status

Check the outcome of a remittance transfer transaction:

```python
with PyMomoSDK(config) as client:
    result = client.remittance.get_transfer_status(reference_id)
    print(f"Remittance status: {result.status}")
```

## Account balance and account holder queries

`Remittance` inherits all shared `BaseProduct` balance and account-holder validation methods:

```python
with PyMomoSDK(config) as client:
    balance = client.remittance.get_balance()
    print(f"Available balance: {balance.available_balance} {balance.currency}")

    ugx_balance = client.remittance.get_balance_for_currency("UGX")
    print(f"UGX balance: {ugx_balance.available_balance} {ugx_balance.currency}")

    is_active = client.remittance.is_account_holder_active("256771234567")
    print(f"Beneficiary active: {is_active}")

    info = client.remittance.get_basic_user_info("256771234567")
    print(f"Beneficiary name: {info.name}")
```

Next step: [Explore Airtel Money](airtel.md).
