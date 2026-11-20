# Webhooks

MTN MoMo uses webhooks (callbacks) to notify your server of transaction updates. When you initiate a write request (such as a request to pay or a transfer) and specify a callback URL, the API sends a `POST` request to that URL containing the transaction details.

## Verifying webhook authenticity

The MTN Developer portal currently does not attach cryptographic request signatures to direct webhook notifications. To defend against spoofed callbacks, always apply layered verification before fulfilling an order:

- **Expose callback endpoints over HTTPS**: Ensure your `callback_url` starts with `https://`.
- **Restrict source IP addresses**: Verify the peer IP address against your allowed gateway IP or CIDR ranges with `WebhookHandler.verify_source_ip`.
- **Verify gateway HMAC signatures**: When running behind a signing proxy or gateway, use `WebhookHandler.verify_hmac_signature` for constant-time HMAC-SHA256 or HMAC-SHA512 verification.
- **Re-query the authoritative MTN status endpoint**: Treat incoming callbacks as notifications and confirm final transaction settlement via `client.collection.get_payment_status(reference_id)` (or the corresponding disbursement or remittance status method) before crediting balances or shipping goods.

### Source IP verification

```python
from py_momo_sdk import WebhookHandler, WebhookVerificationError

allowed_cidrs = ["196.201.214.0/24", "203.0.113.10/32"]

try:
    WebhookHandler.verify_source_ip("196.201.214.42", allowed_cidrs)
except WebhookVerificationError:
    # Reject untrusted source with HTTP 403
    raise
```

### HMAC signature verification

```python
from py_momo_sdk import WebhookHandler, WebhookVerificationError

raw_body = b'{"status":"SUCCESSFUL","amount":"1500.00","currency":"UGX"}'
signature_header = "sha256=<hex-digest-from-header>"
shared_secret = "your-webhook-secret"

try:
    WebhookHandler.verify_hmac_signature(
        raw_body,
        signature_header,
        shared_secret,
        algorithm="sha256",
    )
except WebhookVerificationError:
    # Reject forged or tampered payload with HTTP 401/403
    raise
```

## Processing webhook notifications

Use `WebhookHandler.parse_transaction_notification` to parse and validate incoming webhook JSON payloads into typed `TransactionResult` objects. Invalid payloads raise `WebhookVerificationError`.

```python
from py_momo_sdk import WebhookHandler

webhook_payload = {
    "financialTransactionId": "88771122",
    "externalId": "invoice-9922",
    "amount": "1500.00",
    "currency": "UGX",
    "status": "SUCCESSFUL",
    "payer": {
        "partyIdType": "MSISDN",
        "partyId": "256771234567",
    },
}

result = WebhookHandler.parse_transaction_notification(webhook_payload)
print(f"Status: {result.status}")
print(f"Is successful: {result.is_successful()}")
print(f"Financial transaction ID: {result.financial_transaction_id}")
```

## Quick success checks

To check whether a parsed webhook payload reports a successful status:

```python
if WebhookHandler.is_successful(webhook_payload):
    print("Notification reports successful transaction; verify via status API.")
```

Next step: [Review async client support](async.md).
