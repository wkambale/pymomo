# Command line interface

PyMoMo provides a Typer-based command-line tool named `pymomo` for sandbox provisioning, balance inquiries, and testing.

## Credentials security

The CLI adheres to strict credential security rules:
- Credentials (like subscription keys or API keys) are **never accepted as positional arguments**, preventing them from appearing in shell commands or history.
- Credentials must be passed as command line options (e.g. `--subscription-key`) or as system environment variables.


## Sandbox commands

### Provision a new user and key

Create a sandbox API user and generate its API key:

```bash
pymomo sandbox provision --subscription-key "your-subscription-key" --callback-host "https://pymomo.aiforuganda.org"
```

Output:
```json
{
  "api_user": "api-user-uuid-here",
  "api_key": "api-key-here"
}
```

### Get sandbox user details

Retrieve target environment configuration:

```bash
pymomo sandbox get-user "api-user-uuid-here" --subscription-key "your-subscription-key"
```

Output:
```json
{
  "providerCallbackHost": "https://pymomo.aiforuganda.org",
  "targetEnvironment": "sandbox"
}
```


## Collection commands

### Get collection account balance

Retrieve balance details:

```bash
pymomo collection balance --subscription-key "your-key" --api-user "your-user-uuid" --api-key "your-api-key"
```

Output:
```json
{
  "availableBalance": "1000.00",
  "currency": "EUR"
}
```

### Submit request to pay

Initiate a collection:

```bash
pymomo collection request-to-pay "256771234567" "10.00" "EUR" "inv-100" --subscription-key "your-key" --api-user "your-user-uuid" --api-key "your-api-key"
```

Output:
```json
{
  "reference_id": "initiated-transaction-uuid"
}
```


## Disbursement and remittance commands

### Get disbursement balance

```bash
pymomo disbursement balance --subscription-key "your-key" --api-user "your-user-uuid" --api-key "your-api-key"
```

### Get remittance balance

```bash
pymomo remittance balance --subscription-key "your-key" --api-user "your-user-uuid" --api-key "your-api-key"
```
