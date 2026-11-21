# Error handling

All SDK-specific exceptions inherit from the base `PyMomoSDKError` exception class.

## Exception hierarchy

```
PyMomoSDKError (Base exception)
├── AuthenticationError (Raised on HTTP 401)
├── MissingCredentialsError (Raised when credentials are not configured)
├── BadRequestError (Raised on HTTP 400; includes reason details)
├── ResourceNotFoundError (Raised on HTTP 404)
├── ConflictError (Raised on HTTP 409; duplicate transaction reference)
├── PyMomoSDKServerError (Raised on HTTP 5xx errors)
├── TransactionFailedError (Application-level exception for failed settlements)
└── WebhookVerificationError (Raised on signature, IP, or payload validation failure)
```

Status and settlement polling helpers (`get_payment_status`, `wait_for_settlement`, and `async_wait_for_settlement`) return a typed `TransactionResult` or `PaymentResult` when a transaction settles rather than raising `TransactionFailedError` automatically. Inspect `result.is_failed()` and raise `TransactionFailedError(reference_id, reason=result.reason)` in your application workflow when you want failed settlements to propagate as exceptions.

## Catching exceptions

Catch specific exceptions to handle distinct application states:

```python
from py_momo_sdk import ProductConfig, PyMomoSDK, PyMomoSDKConfig
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
            amount="100.00",
            currency="UGX",
            payer_msisdn="256771234567",
            external_id="invoice-1",
        )
        tx = client.collection.get_payment_status(ref)
        if tx.is_failed():
            raise TransactionFailedError(ref, reason=tx.reason)
    except ValueError as e:
        # Raised immediately on client-side validation errors (e.g. amount="abc")
        print(f"Invalid request input: {e}")
    except BadRequestError as e:
        print(f"Server rejected request: {e}")
        print(f"Details: {e.response_body}")
    except ConflictError:
        print("Duplicate reference ID used.")
    except AuthenticationError:
        print("Authentication credentials rejected.")
    except TransactionFailedError as e:
        print(f"Settlement failed for {e.reference_id}: {e.reason}")
    except PyMomoSDKError as e:
        print(f"Library error occurred: {e}")
```

## Security policies

For security and privacy compliance:
- Secret credentials (`subscription_key`, `api_key`, `client_secret`, `consumer_secret`, `passkey`, `secret_key`, `pin`, `webhook_secret`, and bearer access tokens) are redacted (`<redacted>`) from `__repr__`, `__str__`, and SDK exception messages. Non-secret identifiers such as `api_user` UUIDs and `client_id` values remain visible for troubleshooting.
- Account-holder identifiers in `/accountholder/{type}/{id}` request paths and query strings are redacted from debug logs and `RequestTelemetryEvent` records.
- Transport errors do not chain raw `httpx` exception causes containing request headers.

Next step: [Explore the command line interface](cli.md).
