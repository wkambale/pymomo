# Remittance

The Remittance product executes domestic or international wallet-to-wallet transfers.

## Initializing the remittance client

Access remittance methods via the `.remittance` property of a `PyMomoSDK` instance:

```python
from py_momo_sdk import ProductConfig, PyMomoSDK, PyMomoSDKConfig

config = PyMomoSDKConfig(
    environment="sandbox",
    remittance=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)

client = PyMomoSDK(config)
remittance_client = client.remittance
```

## Transfer

Transfer funds to a beneficiary:

```python
reference_id = client.remittance.transfer(
    amount="250.00",
    currency="UGX",
    payee_msisdn="256771234567",
    external_id="remit-404",
    payer_message="Family support",
    payee_note="Support package",
    # Optional canonical UUID v4; omit to auto-generate
    reference_id="550e8400-e29b-41d4-a716-446655440000",
)
print(f"Remittance reference: {reference_id}")
```

## Get transfer status

Check the outcome of a remittance transfer transaction:

```python
result = client.remittance.get_transfer_status(reference_id)
print(f"Remittance status: {result.status}")
```

## Get account balance

Retrieve the remittance account balance:

```python
balance = client.remittance.get_balance()
print(f"Available balance: {balance.available_balance} {balance.currency}")
```

Next step: [Explore Airtel Money](airtel.md).
