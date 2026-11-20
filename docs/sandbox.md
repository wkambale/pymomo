# Sandbox provisioning

The sandbox environment lets you test your integration without moving live funds. Before making requests to any sandbox product API, provision an API user and an API key.

## Bootstrapping credentials in a single call

The `SandboxProvisioner.provision()` method creates a sandbox API user and generates an API key in a single call:

```python
from py_momo_api import PyMomoAPI, PyMomoAPIConfig

config = PyMomoAPIConfig(environment="sandbox")

with PyMomoAPI(config) as client:
    provisioner = client.create_sandbox_provisioner("your-subscription-key")
    credentials = provisioner.provision(callback_host="https://pymomo.aiforuganda.org")
    print(f"API user UUID: {credentials['api_user']}")
    print(f"API key: {credentials['api_key']}")
```

You can also provision asynchronously with `AsyncPyMomoAPI.create_sandbox_provisioner(...)`:

```python
import asyncio
from py_momo_api import AsyncPyMomoAPI, PyMomoAPIConfig

async def main() -> None:
    config = PyMomoAPIConfig(environment="sandbox")
    async with AsyncPyMomoAPI(config) as client:
        provisioner = client.create_sandbox_provisioner("your-subscription-key")
        credentials = await provisioner.provision(
            callback_host="https://pymomo.aiforuganda.org"
        )
        print(f"API user UUID: {credentials['api_user']}")

asyncio.run(main())
```

Use the generated values as `api_user` and `api_key` in `ProductConfig` when calling product endpoints.

## Detailed provisioning workflow

If you need fine-grained control over sandbox setup, run each provisioning operation individually.

### Create a sandbox API user

Create a new sandbox API user. Supply a canonical UUID v4 or omit `api_user` to generate one automatically:

```python
with PyMomoAPI(config) as client:
    provisioner = client.create_sandbox_provisioner("your-subscription-key")

    # Omit api_user to auto-generate a canonical UUID v4
    api_user = provisioner.create_api_user(
        api_user="550e8400-e29b-41d4-a716-446655440000",
        callback_host="https://your-callback-host.com",
    )
    print(f"API user UUID: {api_user}")
```

### Retrieve API user details

Verify the configuration of an existing sandbox API user:

```python
    user_info = provisioner.get_api_user(api_user)
    print(f"Target environment: {user_info.target_environment}")
    print(f"Provider callback host: {user_info.provider_callback_host}")
```

### Create an API key for the user

Generate the API key used to obtain product access tokens:

```python
    api_key = provisioner.create_api_key(api_user)
    print(f"API key: {api_key}")
```

Next step: [Configure authentication](authentication.md).
