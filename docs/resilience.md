# Resilience and observability

Py MoMo SDK provides bounded idempotent retries, streaming response caps, HTTP redirect rejection, settlement polling, carrier detection, telemetry hooks, framework webhook verifiers, and a local mock gateway for reliable operations and CI testing.

## Idempotent retries and rate limits

Configure `max_retries` and `retry_backoff` on `PyMomoSDKConfig` (or any provider config) to automatically retry transient `429`, `502`, `503`, `504`, timeout, and connection failures with exponential backoff, `secrets`-based jitter, and clamped `Retry-After` handling (numeric seconds and HTTP-date headers, clamped to `30s` max).

To prevent duplicate charges, retries are restricted to safe `GET`, `HEAD`, and `OPTIONS` calls, OAuth token acquisitions, and `POST` write requests where the caller supplies an explicit idempotency key (`reference_id` / `X-Reference-Id` or `Idempotency-Key`). Auto-generated write references are never silently retried on ambiguous failures:

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

## Response size bounds and redirect protection

Every synchronous and asynchronous HTTP client streams responses in chunks and enforces `max_response_bytes` (default `1_048_576` bytes / `1 MiB`) on both `Content-Length` headers and chunked streams without `Content-Length`, preventing memory exhaustion from oversized upstream responses.

All clients disable automatic HTTP redirects (`follow_redirects=False`) and reject `3xx` responses with `PyMomoSDKError`, preventing credential or authorization-header leakage to untrusted redirect targets:

```python
with PyMomoSDK(config, max_response_bytes=524_288) as client:
    balance = client.collection.get_balance()
    print(balance.available_balance)
```

## Settlement polling helpers

Use `wait_for_settlement()` and `async_wait_for_settlement()` (exported from top-level `py_momo_sdk`) to poll until a transaction leaves the pending state with bounded exponential backoff and jitter. Pass `raise_on_failed=True` to convert settled `FAILED` outcomes directly into `TransactionFailedError`:

```python
from py_momo_sdk import wait_for_settlement

settled = wait_for_settlement(
    lambda: client.collection.get_payment_status(reference_id),
    timeout=60.0,
    interval=2.0,
    backoff=1.5,
    raise_on_failed=True,
)
print(settled.status)
```

## Structured telemetry hooks

Implement `TelemetryHook` and pass it to `PyMomoSDKConfig(telemetry=...)`, `AirtelConfig(telemetry=...)`, or any provider config (`WaveConfig`, `MpesaConfig`, `PaystackConfig`, `FlutterwaveConfig`, `OrangeMoneyConfig`) and webhook verifier to forward latencies, attempt counts, error types, and verification outcomes to OpenTelemetry, Prometheus, or structured logs. Exceptions raised inside user telemetry hooks are caught and logged without disrupting payment or webhook execution:

```python
from py_momo_sdk import (
    RequestTelemetryEvent,
    TelemetryHook,
    WebhookTelemetryEvent,
)


class MetricsHook(TelemetryHook):
    def on_request(self, event: RequestTelemetryEvent) -> None:
        print(event.method, event.path, event.status_code, round(event.latency_ms, 2))

    def on_webhook(self, event: WebhookTelemetryEvent) -> None:
        print(event.provider, event.verified, event.reason)
```

## Carrier detection and local mock server

Detect country and mobile money rail prefixes across 18 African markets with `detect_carrier_from_msisdn()`, or spin up the built-in multi-provider local mock gateway in tests with `start_mock_server_thread()`:

```python
from py_momo_sdk import detect_carrier_from_msisdn, start_mock_server_thread

print(detect_carrier_from_msisdn("+256771234567"))  # ("UG", "mtn_momo")

server, state, thread = start_mock_server_thread(port=0, default_status="SUCCESSFUL")
print(server.server_address)
server.shutdown()
server.server_close()
```

Next step: [Review webhook processing](webhooks.md).
