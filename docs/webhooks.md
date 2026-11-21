# Webhooks

MTN MoMo and partner payment gateways use webhooks (callbacks) to notify your server of transaction updates. When you initiate a write request (such as a request to pay or a transfer) and specify a callback URL, the API sends a `POST` request to that URL containing the transaction details.

## Verifying webhook authenticity

The MTN Developer portal currently does not attach cryptographic request signatures to direct webhook notifications. To defend against spoofed callbacks, always apply layered verification before fulfilling an order:

- **Expose callback endpoints over HTTPS**: Ensure your `callback_url` starts with `https://`.
- **Restrict source IP addresses**: Verify the peer IP address against your allowed gateway IP or CIDR ranges with `WebhookHandler.verify_source_ip`.
- **Verify gateway HMAC signatures on raw bytes**: When running behind a signing proxy or receiving signed webhooks from Wave or Paystack, pass the exact raw HTTP request body bytes (`bytes`) to `WebhookHandler.verify_hmac_signature` or `WebhookHandler.verify_timestamped_hmac_signature`. Never parse JSON and re-serialize it with `json.dumps(...)` before checking an HMAC signature, because whitespace or key-order changes invalidate legitimate signatures and can introduce canonicalization bugs.
- **Re-query the authoritative status endpoint**: Treat incoming callbacks as notifications and confirm final transaction settlement via `client.collection.get_payment_status(reference_id)` (or the corresponding disbursement, remittance, or provider status method) before crediting balances or shipping goods.

### Source IP verification and reverse proxies

`WebhookHandler.verify_source_ip`, `create_asgi_webhook_verifier`, and `verify_django_webhook_request` evaluate the direct peer address (`request.client.host` or `REMOTE_ADDR`) rather than trusting raw `X-Forwarded-For` headers, which untrusted clients can spoof. If your application sits behind a reverse proxy or load balancer, configure your server or proxy middleware (such as Uvicorn's `--proxy-headers --forwarded-allow-ips`) to rewrite the client address only from explicitly trusted proxy CIDRs.

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

## Timestamped HMAC signatures and framework helpers

For gateways such as Wave and Stripe that include a replay-protection timestamp (`t=<unix_ts>,v1=<hex>`), use `WebhookHandler.verify_timestamped_hmac_signature()`, or mount `create_asgi_webhook_verifier` in FastAPI (`Depends(...)`, with optional `http_error_status=401` to return a Starlette `HTTPException`) and `verify_django_webhook_request` in Django:

```python
from fastapi import Depends, FastAPI
from py_momo_sdk import create_asgi_webhook_verifier

app = FastAPI()

verify_wave_webhook = create_asgi_webhook_verifier(
    secret="your-webhook-secret",
    signature_header_name="Wave-Signature",
    timestamped=True,
    tolerance_seconds=300,
    http_error_status=401,
)


@app.post("/webhooks/wave")
async def handle_wave_webhook(
    raw_body: bytes = Depends(verify_wave_webhook),
) -> dict[str, bool]:
    return {"received": len(raw_body) > 0}
```

Next step: [Review async client support](async.md).
