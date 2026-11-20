# Resilience and observability

Py MoMo SDK provides transport retries, settlement polling, carrier detection, telemetry hooks, framework webhook verifiers, and a local mock gateway for reliable production operations and CI testing.

## Idempotent retries and rate limits

Configure `max_retries` and `retry_backoff` on `PyMomoSDKConfig` (or provider configs) to automatically retry transient `429`, `502`, `503`, `504`, timeout, and connection failures with exponential backoff, jitter, and `Retry-After` support. Retries are restricted to safe `GET`, `HEAD`, and `OPTIONS` calls or `POST` requests carrying an `X-Reference-Id` header:

```python
from py_momo_sdk import ProductConfig, PyMomoSDK, PyMomoSDKConfig

config = PyMomoSDKConfig(
    environment="sandbox",
    max_retries=2,
    retry_backoff=0.5,
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
    ),
)
```

## Settlement polling helpers

Use `wait_for_settlement()` and `async_wait_for_settlement()` to poll until a transaction leaves the pending state without duplicating backoff loops:

```python
from py_momo_sdk.utils import wait_for_settlement

settled = wait_for_settlement(
    lambda: client.collection.get_payment_status(reference_id),
    timeout=60.0,
    interval=2.0,
    backoff=1.5,
)
print(settled.status)
```

## Structured telemetry hooks

Implement `TelemetryHook` and pass it to `PyMomoSDKConfig(telemetry=...)` to forward request latencies, attempt counts, and HTTP status codes to OpenTelemetry, Prometheus, or structured logs without exposing credentials or PII:

```python
from py_momo_sdk import RequestTelemetryEvent, WebhookTelemetryEvent


class MetricsHook:
    def on_request(self, event: RequestTelemetryEvent) -> None:
        print(event.method, event.path, event.status_code, round(event.latency_ms, 2))

    def on_webhook(self, event: WebhookTelemetryEvent) -> None:
        print(event.provider, event.verified)
```

## Carrier detection and local mock server

Detect country and mobile money rail prefixes with `detect_carrier_from_msisdn()`, or spin up the built-in local mock gateway in tests with `start_mock_server_thread()`:

```python
from py_momo_sdk import start_mock_server_thread
from py_momo_sdk.utils import detect_carrier_from_msisdn

print(detect_carrier_from_msisdn("+256771234567"))  # ("UG", "mtn_momo")

server, state, thread = start_mock_server_thread(port=0, default_status="SUCCESSFUL")
print(server.server_address)
server.shutdown()
server.server_close()
```

Next step: [Review webhook processing](webhooks.md).
