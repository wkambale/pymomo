# Authentication

PyMoMo uses separate configuration records for each product (Collection, Disbursement, Remittance) because the MTN API issues unique credentials for each integration.

## Configuration options

The top-level `MomoConfig` class stores environment selection, timeouts, and product configuration values.

```python
from pymomo import MomoConfig, ProductConfig

config = MomoConfig(
    environment="sandbox",  # Options include sandbox and MTN production country codes
    timeout=30.0,           # Timeout in seconds
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="your-api-user-uuid",
        api_key="your-api-key",
        callback_url="https://your-callback-endpoint.com/webhooks",
    )
)
```

## Loading configuration from environment variables

You can instantiate `MomoConfig` dynamically by loading variables from the system environment using `MomoConfig.from_env()`.

### Supported environment variables

The library automatically checks for the following variables:
- `PYMOMO_ENVIRONMENT`
- `PYMOMO_BASE_URL`
- `PYMOMO_TIMEOUT`
- `PYMOMO_COLLECTION_SUBSCRIPTION_KEY`
- `PYMOMO_COLLECTION_API_USER`
- `PYMOMO_COLLECTION_API_KEY`
- `PYMOMO_COLLECTION_CALLBACK_URL`
- `PYMOMO_DISBURSEMENT_SUBSCRIPTION_KEY`
- `PYMOMO_DISBURSEMENT_API_USER`
- `PYMOMO_DISBURSEMENT_API_KEY`
- `PYMOMO_DISBURSEMENT_CALLBACK_URL`
- `PYMOMO_REMITTANCE_SUBSCRIPTION_KEY`
- `PYMOMO_REMITTANCE_API_USER`
- `PYMOMO_REMITTANCE_API_KEY`
- `PYMOMO_REMITTANCE_CALLBACK_URL`

### Loading example

```python
import os
from pymomo import MomoClient, MomoConfig

# Set some environment variables (typically done outside of Python)
os.environ["PYMOMO_ENVIRONMENT"] = "sandbox"
os.environ["PYMOMO_COLLECTION_SUBSCRIPTION_KEY"] = "your-subscription-key"
os.environ["PYMOMO_COLLECTION_API_USER"] = "your-api-user-uuid"
os.environ["PYMOMO_COLLECTION_API_KEY"] = "your-api-key"

config = MomoConfig.from_env()
with MomoClient(config) as client:
    balance = client.collection.get_balance()
```

## Token caching and automatic refresh

Access tokens are automatically requested, cached in memory, and updated before they expire.
The library handles the token cache internally per product name. When a request returns a `401 Unauthorized` status (due to token expiration or invalidation), the client automatically invalidates the cache, requests a new token, and retries the operation once.
No configuration or cache management is required by the developer.
