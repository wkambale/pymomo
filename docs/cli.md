# Command line interface

Py MoMo API provides a Typer-based command-line tool named `py-momo-api` for sandbox provisioning, balance inquiries, payment initiation, and status checks.

## General options

Show the installed Py MoMo API version:

```bash
py-momo-api --version
```

All API commands also accept `--base-url` (or the `PY_MOMO_API_BASE_URL` environment variable) to target a custom HTTPS endpoint or local mock proxy.

## Credentials security

The CLI adheres to strict credential security rules:
- Credentials (like subscription keys or API keys) are **never accepted as positional arguments**, preventing them from appearing in shell commands or history.
- Credentials must be passed as command line options (e.g. `--subscription-key`) or as system environment variables.


## Sandbox commands

### Provision a new user and key

Create a sandbox API user and generate its API key:

```bash
py-momo-api sandbox provision --subscription-key "your-subscription-key" --callback-host "https://pymomo.aiforuganda.org"
```

Output:
```json
{
  "api_user": "550e8400-e29b-41d4-a716-446655440000",
  "api_key": "api-key-here"
}
```

### Get sandbox user details

Retrieve target environment configuration:

```bash
py-momo-api sandbox get-user "550e8400-e29b-41d4-a716-446655440000" --subscription-key "your-subscription-key"
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
py-momo-api collection balance --subscription-key "your-key" --api-user "550e8400-e29b-41d4-a716-446655440000" --api-key "your-api-key"
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
py-momo-api collection request-to-pay "256771234567" "10.00" "EUR" "inv-100" --subscription-key "your-key" --api-user "550e8400-e29b-41d4-a716-446655440000" --api-key "your-api-key"
```

Output:
```json
{
  "reference_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Check request to pay status

Query the status of a previously submitted Request to Pay transaction:

```bash
py-momo-api collection status "550e8400-e29b-41d4-a716-446655440000" --subscription-key "your-key" --api-user "550e8400-e29b-41d4-a716-446655440000" --api-key "your-api-key"
```

Output:
```json
{
  "financialTransactionId": "88771122",
  "externalId": "inv-100",
  "amount": "10.00",
  "currency": "EUR",
  "status": "SUCCESSFUL"
}
```


## Disbursement and remittance commands

### Get disbursement balance

```bash
py-momo-api disbursement balance --subscription-key "your-key" --api-user "550e8400-e29b-41d4-a716-446655440000" --api-key "your-api-key"
```

### Get remittance balance

```bash
py-momo-api remittance balance --subscription-key "your-key" --api-user "550e8400-e29b-41d4-a716-446655440000" --api-key "your-api-key"
```
