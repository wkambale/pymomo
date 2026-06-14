# Error handling

All exceptions raised by the PyMoMo package inherit from the base `PyMoMoError` exception class.

## Exception hierarchy

```
PyMoMoError (Base exception)
├── AuthenticationError (Raised on HTTP 401)
├── MissingCredentialsError (Raised when credentials are not configured)
├── BadRequestError (Raised on HTTP 400; includes reason details)
├── ResourceNotFoundError (Raised on HTTP 404)
├── ConflictError (Raised on HTTP 409; duplicate UUID reference ID)
├── MomoServerError (Raised on HTTP 5xx errors)
├── TransactionFailedError (Raised on polled transaction failure)
└── WebhookVerificationError (Raised on signature validation failure)
```


## Catching exceptions

Catch specific exceptions to handle distinct application states:

```python
from pymomo import MomoClient, MomoConfig, ProductConfig
from pymomo.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    PyMoMoError,
)

config = MomoConfig(
    environment="sandbox",
    collection=ProductConfig(
        subscription_key="your-key",
        api_user="your-user",
        api_key="your-apikey",
    ),
)

with MomoClient(config) as client:
    try:
        client.collection.request_to_pay(
            amount="abc",  # Invalid amount format will trigger HTTP 400
            currency="UGX",
            payer_msisdn="256771234567",
            external_id="invoice-1",
        )
    except BadRequestError as e:
        print(f"Server rejected request: {e}")
        # Inspect raw API response body returned by the gateway
        print(f"Details: {e.response_body}")
    except ConflictError:
        print("Duplicate reference ID used.")
    except AuthenticationError:
        print("Authentication credentials rejected.")
    except PyMoMoError as e:
        print(f"Library error occurred: {e}")
```

## Security policies

For security and privacy compliance:
- Subscription keys, API user UUIDs, and API keys are redacted or excluded from all exception messages, string formats (`__str__`), and debug records.
- Exception trackbacks do not expose request headers or request bodies.
