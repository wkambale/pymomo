# Authentication

Py MoMo API uses separate configuration records for each product (Collection, Disbursement, Remittance) because the MTN API issues unique credentials for each integration.

## Configuration options

The top-level `PyMomoAPIConfig` class stores environment selection, timeouts, and product configuration values.

```python
from py_momo_api import PyMomoAPIConfig, ProductConfig

config = PyMomoAPIConfig(
    environment="sandbox",  # Options include sandbox and MTN production country codes
    timeout=30.0,           # Timeout in seconds
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
        callback_url="https://your-callback-endpoint.com/webhooks",
    )
)
```

## Loading configuration from environment variables

You can instantiate `PyMomoAPIConfig` dynamically by loading variables from the system environment using `PyMomoAPIConfig.from_env()`.

### Supported environment variables

The library automatically checks for the following variables:
- `PY_MOMO_API_ENVIRONMENT`
- `PY_MOMO_API_BASE_URL`
- `PY_MOMO_API_TIMEOUT`
- `PY_MOMO_API_COLLECTION_SUBSCRIPTION_KEY`
- `PY_MOMO_API_COLLECTION_API_USER`
- `PY_MOMO_API_COLLECTION_API_KEY`
- `PY_MOMO_API_COLLECTION_CALLBACK_URL`
- `PY_MOMO_API_DISBURSEMENT_SUBSCRIPTION_KEY`
- `PY_MOMO_API_DISBURSEMENT_API_USER`
- `PY_MOMO_API_DISBURSEMENT_API_KEY`
- `PY_MOMO_API_DISBURSEMENT_CALLBACK_URL`
- `PY_MOMO_API_REMITTANCE_SUBSCRIPTION_KEY`
- `PY_MOMO_API_REMITTANCE_API_USER`
- `PY_MOMO_API_REMITTANCE_API_KEY`
- `PY_MOMO_API_REMITTANCE_CALLBACK_URL`

### Loading example

```python
import os
from py_momo_api import PyMomoAPI, PyMomoAPIConfig

# Set some environment variables (typically done outside of Python)
os.environ["PY_MOMO_API_ENVIRONMENT"] = "sandbox"
os.environ["PY_MOMO_API_COLLECTION_SUBSCRIPTION_KEY"] = "your-subscription-key"
os.environ["PY_MOMO_API_COLLECTION_API_USER"] = "550e8400-e29b-41d4-a716-446655440000"
os.environ["PY_MOMO_API_COLLECTION_API_KEY"] = "your-api-key"

config = PyMomoAPIConfig.from_env()
with PyMomoAPI(config) as client:
    balance = client.collection.get_balance()
```

## Token caching and automatic refresh

Access tokens are automatically requested, cached in memory, and updated before they expire.
The library handles the token cache internally per product name. When a request returns a `401 Unauthorized` status (due to token expiration or invalidation), the client automatically invalidates the cache, requests a new token, and retries the operation once.
No configuration or cache management is required by the developer.
