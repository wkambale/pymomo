# Error handling

All SDK-specific exceptions inherit from the base `PyMomoSDKError` exception class.

## Exception hierarchy

```
PyMomoSDKError (Base exception)
├── AuthenticationError (Raised on HTTP 401)
├── MissingCredentialsError (Raised when credentials are not configured)
├── BadRequestError (Raised on HTTP 400; includes sanitized message and response_body)
├── ResourceNotFoundError (Raised on HTTP 404)
├── ConflictError (Raised on HTTP 409; carries duplicate reference_id attribute)
├── PyMomoSDKServerError (Raised on HTTP 5xx errors with provider attribution)
├── TransactionFailedError (Raised for failed settlements or wait_for_settlement(..., raise_on_failed=True))
└── WebhookVerificationError (Raised on signature, IP, replay, size, or payload validation failure)
```

Status and settlement polling helpers (`get_payment_status`, `wait_for_settlement`, and `async_wait_for_settlement`) return a typed `TransactionResult` or `PaymentResult` by default. Pass `raise_on_failed=True` to `wait_for_settlement` or `async_wait_for_settlement` to raise `TransactionFailedError` automatically when a transaction settles as failed.

### Transport protection errors

`PyMomoSDKError` is also raised directly when transport safety checks fail:

- **HTTP `3xx` redirects**: Automatic redirects are disabled (`follow_redirects=False`), and `3xx` responses raise `PyMomoSDKError` so authorization headers are never forwarded to another host.
- **Oversized responses (`max_response_bytes`)**: Responses exceeding `max_response_bytes` (default `1 MiB`) on either `Content-Length` or chunked streaming bodies raise `PyMomoSDKError`.
- **Malformed responses**: Non-JSON, non-object JSON, or schema-mismatched `2xx` responses raise `PyMomoSDKError` rather than raw `json.JSONDecodeError` or `pydantic.ValidationError`.

## Catching exceptions

Catch specific exceptions to handle distinct application states:

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
        )
        print(f"Settled: {tx.financial_transaction_id}")
    except ValueError as e:
        # Raised immediately on client-side validation errors (e.g. amount="abc")
        print(f"Invalid request input: {e}")
    except BadRequestError as e:
        print(f"Server rejected request: {e}")
        print(f"Details: {e.response_body}")
    except ConflictError as e:
        print(f"Duplicate reference ID used: {e.reference_id}")
    except AuthenticationError:
        print("Authentication credentials rejected.")
    except TransactionFailedError as e:
        print(f"Settlement failed for {e.reference_id}: {e.reason}")
    except PyMomoSDKError as e:
        print(f"Library error occurred: {e}")
```

## Security policies

For security and privacy compliance:

- Secret credentials (`subscription_key`, `api_key`, `client_secret`, `consumer_secret`, `passkey`, `secret_key`, `pin`, `webhook_secret`, `auth_req_id`, and bearer access tokens) are redacted (`<redacted>`) from `__repr__`, `__str__`, and SDK exception messages.
- Account-holder identifiers in `/accountholder/{type}/{id}`, `/v1_0/apiuser/{id}`, and query strings are redacted from debug logs and `RequestTelemetryEvent` records.
- Transport errors do not chain raw `httpx` exception causes containing request headers.

Next step: [Explore the command line interface](cli.md).
