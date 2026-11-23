# Authentication

Py MoMo SDK uses separate configuration records for each MTN product (`collection`, `disbursement`, and `remittance`) because the MTN API issues unique credentials for each integration.

## Configuration options

`PyMomoSDKConfig` is an immutable dataclass storing environment selection, endpoint overrides, timeouts, retry policy, telemetry hooks, and product credentials:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `environment` | `str` | `SANDBOX` (`"sandbox"`) | Target MTN environment (`X-Target-Environment`). |
| `base_url` | `str \| None` | Auto from `environment` | HTTPS API origin override (HTTP loopback allowed only in sandbox). |
| `timeout` | `float \| httpx.Timeout` | `30.0` | Positive finite request timeout in seconds or `httpx.Timeout`. |
| `max_retries` | `int` | `0` | Maximum transient retries for idempotent requests (`429`, `502`, `503`, `504`, timeouts, connection errors). |
| `retry_backoff` | `float` | `0.5` | Base exponential backoff delay in seconds. |
| `telemetry` | `TelemetryHook \| None` | `None` | Optional observability hook for sanitized request telemetry. |
| `collection` | `ProductConfig \| None` | `None` | Collection subscription key, API user UUID, API key, and optional default `callback_url`. |
| `disbursement` | `ProductConfig \| None` | `None` | Disbursement product credentials. |
| `remittance` | `ProductConfig \| None` | `None` | Remittance product credentials. |

```python
from py_momo_sdk import (
    MTN_UGANDA,
    ProductConfig,
    PyMomoSDKConfig,
)

config = PyMomoSDKConfig(
    environment=MTN_UGANDA,
    timeout=30.0,
    max_retries=2,
    retry_backoff=0.5,
    collection=ProductConfig(
        subscription_key="your-subscription-key",
        api_user="550e8400-e29b-41d4-a716-446655440000",
        api_key="your-api-key",
        callback_url="https://your-callback-endpoint.com/webhooks",
    ),
)
```

## Exported MTN environment constants

Import target environment identifiers from `py_momo_sdk` or `py_momo_sdk.config` instead of hardcoding strings:

- `SANDBOX` (`"sandbox"`)
- `MTN_UGANDA` (`"mtnuganda"`)
- `MTN_GHANA` (`"mtnghana"`)
- `MTN_RWANDA` (`"mtnrwanda"`)
- `MTN_CONGO` (`"mtncongo"`)
- `MTN_IVORY_COAST` (`"mtnivorycoast"`)
- `MTN_CAMEROON` (`"mtncameroon"`)
- `MTN_ZAMBIA` (`"mtnzambia"`)
- `MTN_BENIN` (`"mtnbenin"`)
- `MTN_SWAZILAND` (`"mtnswaziland"`)
- `MTN_GUINEA_CONAKRY` (`"mtnguineaconakry"`)
- `MTN_SOUTH_AFRICA` (`"mtnsouthafrica"`)
- `MTN_LIBERIA` (`"mtnliberia"`)

## Loading configuration from environment variables

You can instantiate `PyMomoSDKConfig` dynamically from environment variables using `PyMomoSDKConfig.from_env()`.

### Supported environment variables

- `PY_MOMO_SDK_ENVIRONMENT`
- `PY_MOMO_SDK_BASE_URL`
- `PY_MOMO_SDK_TIMEOUT`
- `PY_MOMO_SDK_MAX_RETRIES`
- `PY_MOMO_SDK_RETRY_BACKOFF`
- `PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY`
- `PY_MOMO_SDK_COLLECTION_API_USER`
- `PY_MOMO_SDK_COLLECTION_API_KEY`
- `PY_MOMO_SDK_COLLECTION_CALLBACK_URL`
- `PY_MOMO_SDK_DISBURSEMENT_SUBSCRIPTION_KEY`
- `PY_MOMO_SDK_DISBURSEMENT_API_USER`
- `PY_MOMO_SDK_DISBURSEMENT_API_KEY`
- `PY_MOMO_SDK_DISBURSEMENT_CALLBACK_URL`
- `PY_MOMO_SDK_REMITTANCE_SUBSCRIPTION_KEY`
- `PY_MOMO_SDK_REMITTANCE_API_USER`
- `PY_MOMO_SDK_REMITTANCE_API_KEY`
- `PY_MOMO_SDK_REMITTANCE_CALLBACK_URL`

### Loading example

```python
import os
from py_momo_sdk import PyMomoSDK, PyMomoSDKConfig

# Set environment variables (typically configured outside Python)
os.environ["PY_MOMO_SDK_ENVIRONMENT"] = "sandbox"
os.environ["PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY"] = "your-subscription-key"
os.environ["PY_MOMO_SDK_COLLECTION_API_USER"] = "550e8400-e29b-41d4-a716-446655440000"
os.environ["PY_MOMO_SDK_COLLECTION_API_KEY"] = "your-api-key"

config = PyMomoSDKConfig.from_env()
with PyMomoSDK(config) as client:
    balance = client.collection.get_balance()
    print(f"Balance: {balance.available_balance} {balance.currency}")
```

## Token caching and automatic refresh

Access tokens are requested automatically, cached in memory per product and environment namespace with double-checked locking, and refreshed before expiry. When a request returns `401 Unauthorized`, the client conditionally invalidates only the failing token (`expected_token`), fetches a fresh token, and retries the request once while preserving upstream `5xx` errors.

Next step: [Explore Collection](collection.md).
