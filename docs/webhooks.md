# Webhooks

MTN MoMo and partner payment gateways use webhooks (callbacks) to notify your server of transaction updates. Configure a default HTTPS `callback_url` on `ProductConfig` (or provider config), or override `callback_url` per request on write methods (`request_to_pay`, `request_to_withdraw`, `transfer`, `deposit`, `refund`).

## Verifying webhook authenticity

The MTN Developer portal currently does not attach cryptographic request signatures to direct webhook notifications. To defend against spoofed callbacks, always apply layered verification before fulfilling an order:

- **Expose callback endpoints over HTTPS**: Ensure your `callback_url` starts with `https://`.
- **Restrict source IP addresses**: Verify the peer IP address against your allowed gateway IP or CIDR ranges with `WebhookHandler.verify_source_ip`.
- **Verify gateway signatures on raw bytes**: Pass the exact raw HTTP request body bytes (`bytes`) to `WebhookHandler.verify_hmac_signature`, `WebhookHandler.verify_timestamped_hmac_signature`, `verify_raw_webhook_request`, or `verify_static_token_webhook_request`. Never parse JSON and re-serialize it with `json.dumps(...)` before checking an HMAC signature.
- **Re-query the authoritative status endpoint**: Treat incoming callbacks as notifications and confirm final transaction settlement via `client.collection.get_payment_status(reference_id)` (or the corresponding provider status method) before crediting balances or shipping goods.

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

### HMAC and static-token verification

```python
from py_momo_sdk import (
    WebhookHandler,
    WebhookVerificationError,
    verify_constant_time_token,
    verify_raw_webhook_request,
    verify_static_token_webhook_request,
)

raw_body = b'{"status":"SUCCESSFUL","amount":"1500","currency":"UGX"}'
signature_header = "sha256=<hex-digest-from-header>"
shared_secret = "your-webhook-secret"

# Direct HMAC check (SHA-256 or SHA-512)
WebhookHandler.verify_hmac_signature(
    raw_body,
    signature_header,
    shared_secret,
    algorithm="sha256",
)

# Framework-agnostic raw request verification with size bounds and telemetry
verify_raw_webhook_request(
    raw_body=raw_body,
    headers={"X-Signature": signature_header},
    signature_header_name="X-Signature",
    secret=shared_secret,
    remote_ip="196.201.214.42",
    allowed_networks=["196.201.214.0/24"],
    max_body_bytes=1_048_576,
    provider="paystack",
)

# Constant-time static token check (e.g. Flutterwave verif-hash)
verify_constant_time_token("received-hash", "expected-hash")
verify_static_token_webhook_request(
    headers={"verif-hash": "expected-hash"},
    token_header_name="verif-hash",
    expected_token="expected-hash",
    provider="flutterwave",
)
```

## Processing webhook notifications

Use `WebhookHandler.parse_transaction_notification` to parse and validate incoming MTN webhook JSON payloads into typed `TransactionResult` objects. Pass `require_identifier=True` to reject payloads missing both `financialTransactionId` and `externalId`:

```python
from py_momo_sdk import WebhookHandler

webhook_payload = {
    "financialTransactionId": "88771122",
    "externalId": "invoice-9922",
    "amount": "1500",
    "currency": "UGX",
    "status": "SUCCESSFUL",
    "payer": {
        "partyIdType": "MSISDN",
        "partyId": "256771234567",
    },
}

result = WebhookHandler.parse_transaction_notification(
    webhook_payload,
    require_identifier=True,
)
print(f"Status: {result.status}, successful: {result.is_successful()}")
```

## Timestamped HMAC signatures and framework helpers

For gateways such as Wave that sign webhooks with a replay-protection timestamp (`t=<unix_ts>,v1=<hex>`), use `WebhookHandler.verify_timestamped_hmac_signature()` (passing `timestamp_separator=""` for Wave's live `Wave-Signature` format and an optional `replay_check` callback to reject duplicate deliveries).

### FastAPI and Starlette (ASGI)

Install `pip install "py-momo-sdk[fastapi]"` and mount `create_asgi_webhook_verifier` as a dependency. The dependency reads the body stream with `max_body_bytes` enforcement, caches the verified bytes on `request._body` so downstream route handlers can safely call `await request.json()`, and emits `WebhookTelemetryEvent` records when `telemetry` is supplied:

```python
from fastapi import Depends, FastAPI, Request
from py_momo_sdk import create_asgi_webhook_verifier

app = FastAPI()

verify_wave_webhook = create_asgi_webhook_verifier(
    secret="your-wave-webhook-secret",
    signature_header_name="Wave-Signature",
    timestamped=True,
    timestamp_separator="",
    tolerance_seconds=300,
    max_body_bytes=1_048_576,
    http_error_status=401,
    provider="wave",
)


@app.post("/webhooks/wave")
async def handle_wave_webhook(
    request: Request,
    raw_body: bytes = Depends(verify_wave_webhook),
) -> dict[str, object]:
    payload = await request.json()
    return {"received": len(raw_body) > 0, "id": payload.get("id")}
```

### Django

Install `pip install "py-momo-sdk[django]"` and call `verify_django_webhook_request` at the top of your view before parsing `request.body`:

```python
import json
from django.http import HttpRequest, HttpResponse, JsonResponse
from py_momo_sdk import WebhookVerificationError, verify_django_webhook_request


def paystack_webhook_view(request: HttpRequest) -> HttpResponse:
    try:
        raw_body = verify_django_webhook_request(
            request,
            secret="your-paystack-secret-key",
            signature_header_name="x-paystack-signature",
            algorithm="sha512",
            max_body_bytes=1_048_576,
            provider="paystack",
        )
    except WebhookVerificationError:
        return HttpResponse(status=401)

    event = json.loads(raw_body.decode("utf-8"))
    return JsonResponse({"received": True, "event": event.get("event")})
```

Next step: [Review async client support](async.md).
