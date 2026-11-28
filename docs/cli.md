# Command line interface

Py MoMo SDK provides a Typer-based command-line tool named `py-momo-sdk` for sandbox provisioning, balance inquiries, payment initiation, status checks, Airtel PIN encryption, webhook signature verification, carrier prefix inspection, and local mock gateway testing.

Install the CLI extra before invoking `py-momo-sdk`:

```bash
pip install "py-momo-sdk[cli]"
```

## General options

Show the installed Py MoMo SDK version:

```bash
py-momo-sdk --version
```

All MTN API commands accept:

- `-e` / `--environment` (or `PY_MOMO_SDK_ENVIRONMENT`, default `sandbox`)
- `--base-url` (or `PY_MOMO_SDK_BASE_URL`) to target a custom HTTPS endpoint; plaintext `http://` is permitted only for loopback hosts (`localhost`, `127.0.0.1`, `[::1]`) in `sandbox`
- `--timeout`, `--max-retries`, and `--retry-backoff`

## Credentials security

Follow these credential hygiene practices when running `py-momo-sdk`:

- Export secrets via `PY_MOMO_SDK_*` environment variables, or load them from secret files / stdin via `--subscription-key-file`, `--api-key-file`, `--client-secret-file`, `--pin-file`, or `--secret-file` (pass `-` to read from `stdin`).
- Avoid passing raw secrets as CLI flags (`--subscription-key`, `--api-key`), which can appear in shell history and process listings (`ps`).
- Unexpected internal exceptions and validation errors are sanitized before printing to `stderr`.

```bash
export PY_MOMO_SDK_ENVIRONMENT="sandbox"
export PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY="your-subscription-key"
export PY_MOMO_SDK_COLLECTION_API_USER="550e8400-e29b-41d4-a716-446655440000"
export PY_MOMO_SDK_COLLECTION_API_KEY="your-api-key"
```

## Sandbox commands

### Provision a new user and key

Create a sandbox API user and generate its API key (reads `PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY` or `--subscription-key-file`). Use `--output-file` to write credentials with owner-only `0600` permissions, or `--redact-secret` to mask the API key in terminal output:

```bash
py-momo-sdk sandbox provision \
  --callback-host "example.com" \
  --output-file ./sandbox-creds.json \
  --redact-secret
```

Output (without `--redact-secret`):

```json
{
  "api_user": "550e8400-e29b-41d4-a716-446655440000",
  "api_key": "api-key-here"
}
```

### Get sandbox user details

```bash
py-momo-sdk sandbox get-user "550e8400-e29b-41d4-a716-446655440000"
```

## Collection commands

### Get collection account balance

```bash
py-momo-sdk collection balance
py-momo-sdk collection balance --currency UGX
```

Output:

```json
{
  "availableBalance": "1000.00",
  "currency": "EUR"
}
```

### Submit request to pay

Initiate a collection with optional `--payer-message`, `--payee-note`, `--reference-id`, and `--callback-url`:

```bash
py-momo-sdk collection request-to-pay \
  "256771234567" "10.00" "EUR" "inv-100" \
  --payer-message "Invoice 100" \
  --payee-note "Thank you" \
  --reference-id "550e8400-e29b-41d4-a716-446655440000" \
  --callback-url "https://example.com/webhooks/mtn"
```

Output:

```json
{
  "reference_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Check request to pay status

```bash
py-momo-sdk collection status "550e8400-e29b-41d4-a716-446655440000"
```

Output (full `TransactionResult` JSON schema):

```json
{
  "financialTransactionId": "88771122",
  "externalId": "inv-100",
  "amount": "10.00",
  "currency": "EUR",
  "payer": null,
  "payee": null,
  "payerMessage": null,
  "payeeNote": null,
  "status": "SUCCESSFUL",
  "reason": null
}
```

## Disbursement and remittance commands

```bash
# Disbursement balance, transfer, and status
py-momo-sdk disbursement balance
py-momo-sdk disbursement transfer "256771234567" "500" "UGX" "disb-101" \
  --payer-message "Payout" --payee-note "Salary"
py-momo-sdk disbursement status "550e8400-e29b-41d4-a716-446655440000"

# Remittance balance, transfer, and status
py-momo-sdk remittance balance
py-momo-sdk remittance transfer "256771234567" "250" "UGX" "rem-102" \
  --payer-message "Family support" --payee-note "Transfer"
py-momo-sdk remittance status "550e8400-e29b-41d4-a716-446655440000"
```

## Airtel Money commands

```bash
# Encrypt a production disbursement PIN using Airtel's PEM public key
py-momo-sdk airtel encrypt-pin --public-key-file ./airtel_pub.pem --pin-file ./pin.txt

# Query Airtel Money merchant wallet balance
py-momo-sdk airtel balance --country UG --currency UGX
```

## Webhook verification and developer utilities

```bash
# Verify a raw HMAC or timestamped webhook signature from a file or stdin
py-momo-sdk webhook verify \
  --payload-file ./payload.json \
  --signature "t=1700000000,v1=<hex>" \
  --secret-file ./webhook_secret.txt \
  --timestamped \
  --timestamp-separator ""

# Verify a Base64-encoded HMAC-SHA256 webhook signature (e.g. Airtel Money x-signature)
py-momo-sdk webhook verify \
  --payload-file ./airtel_callback.json \
  --signature "<base64-digest>" \
  --secret-file ./airtel_webhook_secret.txt \
  --encoding base64

# Detect MSISDN carrier and country
py-momo-sdk carrier "256771234567"

# Start the local mock gateway server (loopback by default; pass --allow-non-loopback to bind externally)
py-momo-sdk mock --host 127.0.0.1 --port 8090 --status SUCCESSFUL
```

Next step: [Review the changelog](changelog.md).
