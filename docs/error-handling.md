# Error handling

All exceptions raised by the Py MoMo SDK package inherit from the base `PyMomoSDKError` exception class.

## Exception hierarchy

```
PyMomoSDKError (Base exception)
├── AuthenticationError (Raised on HTTP 401)
├── MissingCredentialsError (Raised when credentials are not configured)
├── BadRequestError (Raised on HTTP 400; includes reason details)
├── ResourceNotFoundError (Raised on HTTP 404)
├── ConflictError (Raised on HTTP 409; duplicate UUID reference ID)
├── PyMomoSDKServerError (Raised on HTTP 5xx errors)
├── TransactionFailedError (Raised on polled transaction failure)
└── WebhookVerificationError (Raised on signature validation failure)
```


## Catching exceptions

Catch specific exceptions to handle distinct application states:

```python
from py_momo_sdk import PyMomoSDK, PyMomoSDKConfig, ProductConfig
from py_momo_sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    PyMomoSDKError,
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
        client.collection.request_to_pay(
            amount="100.00",
            currency="UGX",
            payer_msisdn="256771234567",
            external_id="invoice-1",
        )
    except ValueError as e:
        # Raised immediately on client-side validation errors (e.g. amount="abc")
        print(f"Invalid request input: {e}")
    except BadRequestError as e:
        print(f"Server rejected request: {e}")
        # Inspect raw API response body returned by the gateway
        print(f"Details: {e.response_body}")
    except ConflictError:
        print("Duplicate reference ID used.")
    except AuthenticationError:
        print("Authentication credentials rejected.")
    except PyMomoSDKError as e:
        print(f"Library error occurred: {e}")
```

## Security policies

For security and privacy compliance:
- Subscription keys, API user UUIDs, and API keys are redacted or excluded from all exception messages, string formats (`__str__`), and debug records.
- Exception tracebacks do not expose request headers or request bodies.

Next step: [Explore the command line interface](cli.md).
