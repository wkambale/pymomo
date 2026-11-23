# Disbursement

The Disbursement product enables you to send transfers, deposits, and refunds to mobile money subscribers.

## Initializing the disbursement client

Always manage `PyMomoSDK` with a `with` statement (or call `client.close()`) so HTTP connection pools are closed cleanly:

```python
from py_momo_sdk import ProductConfig, PyMomoSDK, PyMomoSDKConfig

config = PyMomoSDKConfig(
    environment="sandbox",
    disbursement=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
        callback_url="https://your-app.example.com/webhooks/disbursement",
    ),
)

with PyMomoSDK(config) as client:
    balance = client.disbursement.get_balance()
    print(f"Balance: {balance.available_balance} {balance.currency}")
```

## Transfer

Transfer funds directly to a subscriber, with optional per-request `callback_url` override:

```python
with PyMomoSDK(config) as client:
    reference_id = client.disbursement.transfer(
        amount="100",
        currency="UGX",
        payee_msisdn="256771234567",
        external_id="transfer-111",
        payer_message="Refund payment",
        payee_note="Refund processed",
        # Optional canonical UUID v4; omit to auto-generate
        reference_id="550e8400-e29b-41d4-a716-446655440000",
        callback_url="https://your-app.example.com/webhooks/transfer-111",
    )
    print(f"Transfer reference: {reference_id}")
```

## Get transfer status

Check the outcome of a transfer transaction:

```python
with PyMomoSDK(config) as client:
    result = client.disbursement.get_transfer_status(reference_id)
    print(f"Transfer status: {result.status}")
```

## Deposit

Deposit funds into a subscriber account (disbursement v2):

```python
with PyMomoSDK(config) as client:
    reference_id = client.disbursement.deposit(
        amount="500",
        currency="UGX",
        payee_msisdn="256771234567",
        external_id="deposit-202",
        payer_message="Salary deposit",
        payee_note="June salary",
        reference_id="550e8400-e29b-41d4-a716-446655440000",
        callback_url="https://your-app.example.com/webhooks/deposit-202",
    )
    print(f"Deposit reference: {reference_id}")
```

## Get deposit status

Check the outcome of a deposit transaction:

```python
with PyMomoSDK(config) as client:
    result = client.disbursement.get_deposit_status(reference_id)
    print(f"Deposit status: {result.status}")
```

## Refund

Issue a refund for a previously settled transaction (disbursement v2):

```python
with PyMomoSDK(config) as client:
    reference_id = client.disbursement.refund(
        amount="50",
        currency="UGX",
        reference_id_to_refund="6ba7b810-9dad-41d1-80b4-00c04fd430c8",
        external_id="refund-303",
        payer_message="Return refund",
        payee_note="Product returned",
        reference_id="550e8400-e29b-41d4-a716-446655440000",
        callback_url="https://your-app.example.com/webhooks/refund-303",
    )
    print(f"Refund reference: {reference_id}")
```

## Get refund status

Check the outcome of a refund transaction:

```python
with PyMomoSDK(config) as client:
    result = client.disbursement.get_refund_status(reference_id)
    print(f"Refund status: {result.status}")
```

## Account balance and account holder queries

`Disbursement` inherits all shared `BaseProduct` balance and account-holder validation methods:

```python
with PyMomoSDK(config) as client:
    balance = client.disbursement.get_balance()
    print(f"Available balance: {balance.available_balance} {balance.currency}")

    ugx_balance = client.disbursement.get_balance_for_currency("UGX")
    print(f"UGX balance: {ugx_balance.available_balance} {ugx_balance.currency}")

    is_active = client.disbursement.is_account_holder_active("256771234567")
    print(f"Payee active: {is_active}")

    info = client.disbursement.get_basic_user_info("256771234567")
    print(f"Payee name: {info.name}")
```

Next step: [Explore Remittance](remittance.md).
