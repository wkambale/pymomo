# Disbursement

The Disbursement product enables you to transfer funds, deposits, and refunds to mobile money subscribers.

## Initializing disbursement client

Access disbursement methods via the `.disbursement` property of a `MomoClient` instance:

```python
from pymomo import MomoClient, MomoConfig, ProductConfig

config = MomoConfig(
    environment="sandbox",
    disbursement=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="your-api-user-uuid",
        api_key="your-api-key",
    ),
)

client = MomoClient(config)
disbursement_client = client.disbursement
```

---

## Transfer

Transfer funds directly to a subscriber.

```python
reference_id = client.disbursement.transfer(
    amount="100.00",
    currency="UGX",
    payee_msisdn="256771234567",
    external_id="transfer-111",
    payer_message="Refund payment",
    payee_note="Refund processed",
    reference_id="optional-custom-uuid",
)
print(f"Transfer Reference: {reference_id}")
```

## Get transfer status

Check the outcome of a transfer transaction.

```python
result = client.disbursement.get_transfer_status(reference_id)
print(f"Transfer status: {result.status}")
```

---

## Deposit

Deposit funds into a subscriber's account (disbursement v2).

```python
reference_id = client.disbursement.deposit(
    amount="500.00",
    currency="UGX",
    payee_msisdn="256771234567",
    external_id="deposit-202",
    payer_message="Salary deposit",
    payee_note="June salary",
    reference_id="optional-custom-uuid",
)
print(f"Deposit Reference: {reference_id}")
```

## Get deposit status

Check the outcome of a deposit transaction.

```python
result = client.disbursement.get_deposit_status(reference_id)
print(f"Deposit status: {result.status}")
```

---

## Refund

Issue a refund for a previously settled transaction (disbursement v2).

```python
reference_id = client.disbursement.refund(
    amount="50.00",
    currency="UGX",
    reference_id_to_refund="previous-transaction-uuid",
    external_id="refund-303",
    payer_message="Return refund",
    payee_note="Product returned",
    reference_id="optional-custom-uuid",
)
print(f"Refund Reference: {reference_id}")
```

## Get refund status

Check the outcome of a refund transaction.

```python
result = client.disbursement.get_refund_status(reference_id)
print(f"Refund status: {result.status}")
```

---

## Get account balance

Retrieve the disbursement account balance.

```python
balance = client.disbursement.get_balance()
print(f"Available balance: {balance.available_balance} {balance.currency}")
```

## Check if account holder is active

Validate whether a payee account is registered and active.

```python
is_active = client.disbursement.is_account_holder_active("256771234567")
print(f"Payee active: {is_active}")
```
