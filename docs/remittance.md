# Remittance

The Remittance product allows you to execute domestic or international wallet-to-wallet transfers.

## Initializing remittance client

Access remittance methods via the `.remittance` property of a `MomoClient` instance:

```python
from pymomo import MomoClient, MomoConfig, ProductConfig

config = MomoConfig(
    environment="sandbox",
    remittance=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="your-api-user-uuid",
        api_key="your-api-key",
    ),
)

client = MomoClient(config)
remittance_client = client.remittance
```


## Transfer

Transfer funds to a beneficiary.

```python
reference_id = client.remittance.transfer(
    amount="250.00",
    currency="UGX",
    payee_msisdn="256771234567",
    external_id="remit-404",
    payer_message="Family support",
    payee_note="Support package",
    reference_id="optional-custom-uuid",
)
print(f"Remittance Reference: {reference_id}")
```

## Get transfer status

Check the outcome of a remittance transfer transaction.

```python
result = client.remittance.get_transfer_status(reference_id)
print(f"Remittance status: {result.status}")
```


## Get account balance

Retrieve the remittance account balance.

```python
balance = client.remittance.get_balance()
print(f"Available balance: {balance.available_balance} {balance.currency}")
```
