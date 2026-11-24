# Error handling

All SDK-specific exceptions inherit from the base `PyMomoSDKError` exception class.

## Exception hierarchy

```
PyMomoSDKError (Base exception; carries reference_id, status_code, error_code, reason, response_body, provider, attempted_references)
├── AuthenticationError (Raised on HTTP 401 with upstream error detail)
├── MissingCredentialsError (Raised when credentials are not configured)
├── BadRequestError (Raised on HTTP 400 and 422; includes sanitized message, error_code, and redacted response_body)
├── ResourceNotFoundError (Raised on HTTP 404 with upstream error detail)
├── ConflictError (Raised on HTTP 409; carries duplicate reference_id attribute)
├── PyMomoSDKServerError (Raised on HTTP 5xx errors with provider attribution and upstream error detail)
├── TransactionFailedError (Raised for failed settlements or wait_for_settlement(..., raise_on_failed=True))
└── WebhookVerificationError (Raised on signature, IP, replay, size, or payload validation failure)
```

Status and settlement polling helpers (`get_payment_status`, `wait_for_settlement`, and `async_wait_for_settlement`) return a typed `TransactionResult` or `PaymentResult` by default. Pass `raise_on_failed=True` and `reference_id=ref` to `wait_for_settlement` or `async_wait_for_settlement` so raised `TransactionFailedError` and polling timeout exceptions always carry the payment reference ID.

### Structured error attributes

Every `PyMomoSDKError` instance (and every subclass) exposes structured attributes so callers can reconcile failed payments and log clear failure reasons without scraping exception text:

- **`reference_id`**: The caller-supplied or auto-generated payment reference ID associated with the failed request (preserved across HTTP `4xx`/`5xx`, timeouts, connection errors, OAuth2 token failures, and response parsing errors across all 7 providers).
- **`status_code`**: The upstream HTTP status code (for example `400`, `401`, `403`, `404`, `409`, `422`, `429`, or `500`), or `None` for transport failures.
- **`error_code`**: The machine-readable upstream error code extracted from the gateway response (such as MTN `code`, Airtel `status.result_code`, M-Pesa `errorCode`, Wave `code`, or OAuth2 `error`).
- **`reason`**: The sanitized human-readable failure reason from the gateway response, or the safe `httpx` transport subtype name (such as `ReadTimeout` or `ConnectError`) on network errors.
- **`response_body`**: A sanitized dictionary of the upstream JSON payload with sensitive keys (`access_token`, `client_secret`, `api_key`, `pin`, `authorization`, `password`, etc.) recursively replaced with `<redacted>` and omitted from `repr()`.
- **`provider`**: The upstream payment rail name (for example `"MTN MoMo"`, `"Airtel Money"`, `"Wave"`, `"M-Pesa"`, `"Paystack"`, `"Flutterwave"`, or `"Orange Money"`).
- **`attempted_references`**: On `PaymentRouter` and `AsyncPaymentRouter` failover exhaustion, a list of `{"provider": ..., "reference_id": ...}` records for every rail attempted.

### Transport protection errors

`PyMomoSDKError` is also raised directly when transport safety checks fail:

- **HTTP `3xx` redirects**: Automatic redirects are disabled (`follow_redirects=False`), and `3xx` responses raise `PyMomoSDKError` so authorization headers are never forwarded to another host.
- **Oversized responses (`max_response_bytes`)**: Responses exceeding `max_response_bytes` (default `1 MiB`) on either `Content-Length` or chunked streaming bodies raise `PyMomoSDKError`.
- **Malformed responses**: Non-JSON, non-object JSON, or schema-mismatched `2xx` responses raise `PyMomoSDKError` rather than raw `json.JSONDecodeError` or `pydantic.ValidationError`.

## Catching exceptions

Catch specific exceptions to handle distinct application states and reconcile failed writes using `e.reference_id`, `e.error_code`, and `e.reason`:

```python
from py_momo_sdk import (
    ProductConfig,
    PyMomoSDK,
    PyMomoSDKConfig,
    wait_for_settlement,
)
from py_momo_sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    PyMomoSDKError,
    TransactionFailedError,
)

config = PyMomoSDKConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-apikey",
    ),
)

with PyMomoSDK(config) as client:
    try:
        ref = client.collection.request_to_pay(
            amount="100",
            currency="UGX",
            payer_msisdn="256771234567",
            external_id="invoice-1",
        )
        tx = wait_for_settlement(
            lambda: client.collection.get_payment_status(ref),
            timeout=60.0,
            raise_on_failed=True,
            reference_id=ref,
        )
        print(f"Settled: {tx.financial_transaction_id}")
    except ValueError as e:
        # Raised immediately on client-side validation errors (e.g. amount="abc")
        print(f"Invalid request input: {e}")
    except BadRequestError as e:
        print(f"Server rejected {e.reference_id} ({e.error_code}): {e.reason}")
        print(f"Details: {e.response_body}")
    except ConflictError as e:
        print(f"Duplicate reference ID used: {e.reference_id}")
    except AuthenticationError as e:
        print(f"Authentication rejected for {e.reference_id}: {e.reason}")
    except TransactionFailedError as e:
        print(f"Settlement failed for {e.reference_id}: {e.reason}")
    except PyMomoSDKError as e:
        print(f"Payment {e.reference_id} failed ({e.status_code}): {e}")
```

## Security policies

For security and privacy compliance:

- Secret credentials (`subscription_key`, `api_key`, `client_secret`, `consumer_secret`, `passkey`, `secret_key`, `pin`, `webhook_secret`, `auth_req_id`, and bearer access tokens) are redacted (`<redacted>`) from `__repr__`, `__str__`, and SDK exception messages.
- Account-holder identifiers in `/accountholder/{type}/{id}`, `/v1_0/apiuser/{id}`, and query strings are redacted from debug logs and `RequestTelemetryEvent` records.
- Transport errors do not chain raw `httpx` exception causes containing request headers.

Next step: [Explore the command line interface](cli.md).
