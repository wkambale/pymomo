# Command line interface

Py MoMo SDK provides a Typer-based command-line tool named `py-momo-sdk` for sandbox provisioning, balance inquiries, payment initiation, status checks, carrier prefix inspection, and local mock gateway testing.

## General options

Show the installed Py MoMo SDK version:

```bash
py-momo-sdk --version
```

All API commands also accept `--base-url` (or the `PY_MOMO_SDK_BASE_URL` environment variable) to target a custom HTTPS endpoint or local mock proxy.

## Credentials security

Follow these credential hygiene practices when running `py-momo-sdk`:
- Export secrets via `PY_MOMO_SDK_*` environment variables rather than passing `--subscription-key` or `--api-key` directly on the command line. Command-line flags are recorded in shell history files and are visible to other local users in process listings (`ps`).
- Credentials are never accepted as positional arguments, and unexpected internal exceptions are sanitized before printing to `stderr`.

```bash
export PY_MOMO_SDK_ENVIRONMENT="sandbox"
export PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY="your-subscription-key"
export PY_MOMO_SDK_COLLECTION_API_USER="550e8400-e29b-41d4-a716-446655440000"
export PY_MOMO_SDK_COLLECTION_API_KEY="your-api-key"
```

## Sandbox commands

### Provision a new user and key

Create a sandbox API user and generate its API key (reads `PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY` from the environment):

```bash
py-momo-sdk sandbox provision --callback-host "https://example.com"
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
py-momo-sdk sandbox get-user "550e8400-e29b-41d4-a716-446655440000"
```

Output:
```json
{
  "providerCallbackHost": "https://example.com",
  "targetEnvironment": "sandbox"
}
```

## Collection commands

### Get collection account balance

Retrieve balance details using exported `PY_MOMO_SDK_COLLECTION_*` environment variables:

```bash
py-momo-sdk collection balance
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
py-momo-sdk collection request-to-pay "256771234567" "10.00" "EUR" "inv-100"
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
py-momo-sdk collection status "550e8400-e29b-41d4-a716-446655440000"
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
export PY_MOMO_SDK_DISBURSEMENT_SUBSCRIPTION_KEY="your-disbursement-key"
export PY_MOMO_SDK_DISBURSEMENT_API_USER="550e8400-e29b-41d4-a716-446655440000"
export PY_MOMO_SDK_DISBURSEMENT_API_KEY="your-disbursement-api-key"

py-momo-sdk disbursement balance
```

### Get remittance balance

```bash
export PY_MOMO_SDK_REMITTANCE_SUBSCRIPTION_KEY="your-remittance-key"
export PY_MOMO_SDK_REMITTANCE_API_USER="550e8400-e29b-41d4-a716-446655440000"
export PY_MOMO_SDK_REMITTANCE_API_KEY="your-remittance-api-key"

py-momo-sdk remittance balance
```

## Developer utilities

### Detect MSISDN carrier and country

```bash
py-momo-sdk carrier "256771234567"
```

### Start the local mock gateway server

```bash
py-momo-sdk mock --host 127.0.0.1 --port 8090 --status SUCCESSFUL
```

Next step: [Review the changelog](changelog.md).
