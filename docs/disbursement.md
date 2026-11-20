# Disbursement

The Disbursement product enables you to send transfers, deposits, and refunds to mobile money subscribers.

## Initializing the disbursement client

Access disbursement methods via the `.disbursement` property of a `PyMomoAPI` instance:

```python
from py_momo_api import ProductConfig, PyMomoAPI, PyMomoAPIConfig

config = PyMomoAPIConfig(
    environment="sandbox",
    disbursement=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)

client = PyMomoAPI(config)
disbursement_client = client.disbursement
```

## Transfer

Transfer funds directly to a subscriber:

```python
reference_id = client.disbursement.transfer(
    amount="100.00",
    currency="UGX",
    payee_msisdn="256771234567",
    external_id="transfer-111",
    payer_message="Refund payment",
    payee_note="Refund processed",
    # Optional canonical UUID v4; omit to auto-generate
    reference_id="550e8400-e29b-41d4-a716-446655440000",
)
print(f"Transfer reference: {reference_id}")
```

## Get transfer status

Check the outcome of a transfer transaction:

```python
result = client.disbursement.get_transfer_status(reference_id)
print(f"Transfer status: {result.status}")
```

## Deposit

Deposit funds into a subscriber account (disbursement v2):

```python
reference_id = client.disbursement.deposit(
    amount="500.00",
    currency="UGX",
    payee_msisdn="256771234567",
    external_id="deposit-202",
    payer_message="Salary deposit",
    payee_note="June salary",
    # Optional canonical UUID v4; omit to auto-generate
    reference_id="550e8400-e29b-41d4-a716-446655440000",
)
print(f"Deposit reference: {reference_id}")
```

## Get deposit status

Check the outcome of a deposit transaction:

```python
result = client.disbursement.get_deposit_status(reference_id)
print(f"Deposit status: {result.status}")
```

## Refund

Issue a refund for a previously settled transaction (disbursement v2):

```python
reference_id = client.disbursement.refund(
    amount="50.00",
    currency="UGX",
    reference_id_to_refund="6ba7b810-9dad-41d1-80b4-00c04fd430c8",
    external_id="refund-303",
    payer_message="Return refund",
    payee_note="Product returned",
    # Optional canonical UUID v4; omit to auto-generate
    reference_id="550e8400-e29b-41d4-a716-446655440000",
)
print(f"Refund reference: {reference_id}")
```

## Get refund status

Check the outcome of a refund transaction:

```python
result = client.disbursement.get_refund_status(reference_id)
print(f"Refund status: {result.status}")
```

## Get account balance

Retrieve the disbursement account balance:

```python
balance = client.disbursement.get_balance()
print(f"Available balance: {balance.available_balance} {balance.currency}")
```

## Check if account holder is active

Validate whether a payee account is registered and active:

```python
is_active = client.disbursement.is_account_holder_active("256771234567")
print(f"Payee active: {is_active}")
```

Next step: [Explore Remittance](remittance.md).
