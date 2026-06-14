# Webhooks

MTN MoMo uses webhooks (callbacks) to notify your server of transaction updates. When you initiate a write request (like a request to pay or a transfer) and specify a callback URL, the API sends a `POST` request to that URL containing the final transaction details.

## Webhook signature validation

The MTN Developer portal currently does not attach cryptographic request signatures to webhook notifications. To ensure callbacks originate securely from the MTN platform, you must:

1.  **Expose callback endpoints over HTTPS**: Ensure your callback URL starts with `https://`.
2.  **Filter incoming IP addresses**: Restrict incoming traffic to your webhook endpoints so that only requests originating from official MTN API gateway IP addresses are allowed.

---

## Processing webhook notifications

Use the `WebhookHandler` class to parse incoming webhook JSON payloads into typed model objects:

```python
from pymomo import WebhookHandler

# Example webhook payload received by your web server
webhook_payload = {
    "financialTransactionId": "88771122",
    "externalId": "invoice-9922",
    "amount": "1500.00",
    "currency": "UGX",
    "status": "SUCCESSFUL",
    "payer": {
        "partyIdType": "MSISDN",
        "partyId": "256771234567"
    }
}

# Parse payload into a TransactionResult object
result = WebhookHandler.parse_transaction_notification(webhook_payload)

print(f"Status: {result.status}")
print(f"Is successful: {result.is_successful()}")
print(f"Financial Transaction ID: {result.financial_transaction_id}")
```

## Quick success checks

If you only need to determine if a webhook call indicates a successful transaction without parsing other fields:

```python
is_ok = WebhookHandler.is_successful(webhook_payload)
if is_ok:
    print("Transaction settled successfully.")
```
