# Sandbox provisioning

The sandbox environment allows testing your integration without moving actual funds. Before you can make requests to any sandbox product API, you must provision an API user and an API key.

## Bootstrapping credentials in a single call

The `SandboxProvisioner.provision()` method creates a sandbox API user and generates an API key in a single transaction:

```python
from pymomo import MomoClient, MomoConfig, SandboxProvisioner

config = MomoConfig(environment="sandbox")

with MomoClient(config) as client:
    # Initialize the provisioner with your sandbox subscription key
    provisioner = SandboxProvisioner(
        subscription_key="your-subscription-key",
        config=config,
        http=client._http,
    )
    
    # Provision credentials
    credentials = provisioner.provision(callback_host="https://webhook.site")
    print(f"API User UUID: {credentials['api_user']}")
    print(f"API Key: {credentials['api_key']}")
```

You can now use these generated values as the `api_user` and `api_key` properties in `ProductConfig` when making product client requests.

---

## Detailed provisioning steps

If you need fine-grained control over the sandbox environment setup, you can run the provisioning steps individually.

### Step 1: Create a sandbox API user

Create a new sandbox API user. You can supply a custom UUID or let the library generate one automatically:

```python
with MomoClient(config) as client:
    provisioner = SandboxProvisioner(
        subscription_key="your-subscription-key",
        config=config,
        http=client._http,
    )
    
    # Create the user and get back the UUID
    api_user = provisioner.create_api_user(
        api_user="optional-custom-uuid",
        callback_host="https://your-callback-host.com",
    )
    print(f"API User UUID: {api_user}")
```

### Step 2: Retrieve API user details

Verify the configuration of a sandbox API user:

```python
    user_info = provisioner.get_api_user(api_user)
    print(f"Target Environment: {user_info.target_environment}")
    print(f"Provider Callback Host: {user_info.provider_callback_host}")
```

### Step 3: Create an API key for the user

Generate the API key used to authenticate request tokens:

```python
    api_key = provisioner.create_api_key(api_user)
    print(f"API Key: {api_key}")
```
