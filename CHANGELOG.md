# Changelog

All notable changes to the Py MoMo SDK (`py-momo-sdk`) project will be documented in this file.

## 1.3.1 - 2026-11-24

### Fixed
- Preserved the payment `reference_id` (both caller-supplied and auto-generated) on every failed request across all 7 payment rails (MTN MoMo, Airtel Money, Wave, Safaricom M-Pesa, Paystack, Flutterwave, and Orange Money) in both synchronous and asynchronous clients, including HTTP `4xx`/`5xx` errors, timeouts, connection errors, response-size rejections, OAuth2 token acquisition/refresh failures, and JSON/schema parsing errors.
- Surfaced clear, structured upstream failure diagnostics on `PyMomoSDKError` and all subclasses via `reference_id`, `status_code`, `error_code`, `reason`, secret-redacted `response_body`, `provider`, and `attempted_references` across all 7 gateway error schemas (including HTTP `422` validation errors mapped to `BadRequestError`, Airtel HTTP `200` `status.result_code` rejections, sanitized plain-text bodies with HTML suppression, and safe transport exception subtypes such as `(ReadTimeout)` and `(ConnectError)` without chaining raw request headers).
- Attached `attempted_references` on `PaymentRouter` and `AsyncPaymentRouter` failover exhaustion, added `reference_id` support to `wait_for_settlement()` and `async_wait_for_settlement()`, and included `(reference_id: ...)` in CLI error output.

## 1.3.0 - 2026-11-23

### Added
- Exported all 13 MTN environment constants (`SANDBOX`, `MTN_UGANDA`, `MTN_GHANA`, `MTN_RWANDA`, `MTN_CONGO`, `MTN_IVORY_COAST`, `MTN_CAMEROON`, `MTN_ZAMBIA`, `MTN_BENIN`, `MTN_SWAZILAND`, `MTN_GUINEA_CONAKRY`, `MTN_SOUTH_AFRICA`, `MTN_LIBERIA`), `detect_carrier_from_msisdn`, `wait_for_settlement`, `async_wait_for_settlement`, and `verify_static_token_webhook_request` from top-level `py_momo_sdk`.
- Added optional packaging extras in `pyproject.toml`: `[cli]`, `[airtel]`, `[fastapi]`, `[django]`, and `[all]`, PEP 639 SPDX license metadata, and build provenance attestation + SHA-256 checksums in release publishing.
- Added `OrangePaymentContextStore` pluggable store support and stateless `get_status(..., order_id, amount, currency)` on `OrangeMoneyProvider` / `AsyncOrangeMoneyProvider`, `PaymentRouter` / `AsyncPaymentRouter` `threading.RLock` safety, failover reconciliation (`prior_failed_attempts`), 18-market pan-African carrier prefix mapping with `custom_carrier_prefixes`, and context-managed lifecycle `close()` / `aclose()` across all providers and routers.
- Expanded CLI with `disbursement transfer`/`status`, `remittance transfer`/`status`, `airtel encrypt-pin`/`balance`, `webhook verify`, `--*-file` / stdin secret loading, `--output-file` (`0600`), `--redact-secret`, and resilience flags (`--timeout`, `--max-retries`, `--retry-backoff`); expanded `mock_server` with IPv6 `::1`, chunked decoding, bounded concurrency semaphore, MTN `409 Conflict`, and multi-provider routes.

### Security
- Blocked SSRF private/metadata/obfuscated IP hosts, percent-encoded path traversal, non-ASCII header injection, mismatched injected client origins, and localhost URLs in production environments; froze configuration dataclasses against post-init mutation.
- Extended secret redaction across telemetry paths (`/v1_0/apiuser/<redacted>`), `ProductConfig`, `BcAuthorizeResponse`, `ProvisionResult`, reference ID validators, and sanitized `BadRequestError` messages.
- Protected webhook and ASGI/Django verifiers against oversized header/timestamp/`Content-Length` DoS, duplicate multi-dict headers, non-short-circuiting multi-`v1` comparisons, replay delivery (`replay_check`), IPv6 zone IDs, and stream-consumption issues via Starlette `request._body` caching.

### Fixed
- Aligned provider contracts with live API specifications: MTN `ErrorReason` object parsing, strict E.164 MSISDN and zero-decimal currency amount validation, CIBA OAuth2 `refresh_token` grant, `wait_for_settlement` deadline accuracy, Airtel country-aware MSISDN and HTTP 200 business-error inspection, M-Pesa Daraja EAT (`UTC+3`) timestamps / whole-integer KES amounts / B2C v3 `OriginatorConversationID`, Wave live `receive_amount` and no-dot `Wave-Signature` (`timestamp_separator=""`), Flutterwave alphanumeric bank/IBAN preservation and currency balances, Paystack multi-currency balance selection and zero-decimal guards, and core transport explicit `idempotent` retry safety with CAS 401 token refresh and per-loop async locks.
- Fixed false-positive Airtel amount and webhook telemetry isolation tests, added genuine chunked-stream, real `cryptography`/`FastAPI`/`Django`, and multi-threaded/asyncio concurrency and stress tests (lifting total coverage to **95%**).
- Fixed MkDocs duplicate scroll-to-top button and `docs/javascripts/scroll.js` instant-navigation `scroll` listener leak, cleaned editorial wording, and updated all guides and `README.md`.

## 1.2.0 - 2026-11-21

### Added
- Exported `py_momo_sdk.__version__`, `encrypt_airtel_pin()`, per-request `callback_url` overrides across MTN Collection, Disbursement, and Remittance write methods, `payer_email` and `payee_bank_code` on unified provider DTOs, `verify_transfer()` on Paystack clients, `get_transfer()` on Flutterwave clients, and `verify_webhook()` / `verify_webhook_hash()` on async Wave, Paystack, and Flutterwave clients.
- Brought `AirtelClient` and `AsyncAirtelClient` to full transport parity with injectable `httpx` clients, `max_retries` and `retry_backoff`, `TelemetryHook` observability, bounded streaming response reads, and safe alphanumeric `reference_id` support.

### Security
- Prevented automatic `PaymentRouter` and `AsyncPaymentRouter` failover on ambiguous `5xx` or network write failures unless `allow_ambiguous_write_fallback=True` is explicitly set, while keeping safe pre-flight failover on authentication and missing-credential errors; enforced capability and currency filtering during candidate resolution.
- Rejected HTTP `3xx` redirects in `_raise_for_status` and Airtel clients, validated injected `httpx` client base URLs and per-request `follow_redirects=False`, and enforced a streaming `max_response_bytes` cap (`1 MiB` default) across sync and async HTTP clients.
- Protected `WebhookHandler`, `create_asgi_webhook_verifier`, `verify_django_webhook_request`, and `verify_constant_time_token` against non-ASCII `compare_digest` errors, oversized request bodies, spoofed or IPv4-mapped IPv6 addresses, duplicate `t=` or signature headers, non-finite `tolerance_seconds`, and future timestamp skew.
- Validated per-request callback/redirect URLs, `base_url`, `max_retries`, `retry_backoff`, and `"sandbox"` vs `"production"` environment names across all provider configurations and direct client write methods; removed `example.com` default callback URLs and production `"testapi"` initiator defaults; guarded Airtel production configurations against plaintext numeric PINs.
- Added `allowed_plugins` allowlisting and protocol validation to `discover_provider_plugins()`, secured `mock_server` with body-size and state-entry caps, socket timeouts, thread locking, and non-loopback bind protection, redacted `/accountholder/{type}/{id}` PII in logs and telemetry events, and isolated GitHub Actions `verify`, `build`, and `publish` / `deploy-pages` jobs without `contents: write`.

### Fixed
- Fixed Airtel disbursement payload schema (`{payee, transaction, reference, pin}`), Airtel currency validation, Orange Money country `api_path_prefix` and `(order_id, amount)` status tracking, Paystack minor-unit precision and envelope checks, Flutterwave explicit `email` and `account_bank` handling, `kind` validation across all 7 providers, status mappings (`REVERSED`, `EXPIRED`, `CANCELLED`, indeterminate `PENDING`), and documentation/CLI credential guidance.

## 1.1.0 - 2026-11-21

### Added
- Asynchronous Airtel Money client (`AsyncAirtelClient`, `AsyncAirtelAuth`, `AsyncAirtelCollection`, `AsyncAirtelDisbursement`).
- Unified multi-provider orchestration (`PaymentProvider`, `AsyncPaymentProvider`, `PaymentRouter`, `AsyncPaymentRouter`, normalized DTOs, and `py_momo_sdk.providers` entry-point plugin discovery).
- First-class provider clients and adapters for Wave, Safaricom M-Pesa (Daraja), Paystack, Flutterwave, and Orange Money alongside MTN MoMo and Airtel Money.
- Bounded idempotent retries with `Retry-After` and `secrets`-based jitter (`max_retries`, `retry_backoff`), injectable `httpx` clients, `wait_for_settlement()` and `async_wait_for_settlement()`, `detect_carrier_from_msisdn()`, and `TelemetryHook` observability events.
- Timestamped HMAC webhook verification (`WebhookHandler.verify_timestamped_hmac_signature`), FastAPI/Starlette and Django raw-body webhook verifiers, local mock gateway server (`start_mock_server_thread` and `py-momo-sdk mock`), and `py-momo-sdk carrier`.
- New documentation guides for multi-provider orchestration (`docs/providers.md`) and resilience and observability (`docs/resilience.md`).

## 1.0.6 - 2026-11-20

### Changed
- Renamed the brand, PyPI distribution, Python package, classes, CLI command, and environment variables from `Py MoMo API` / `py-momo-api` / `py_momo_api` / `PyMomoAPI` to **Py MoMo SDK** (`py-momo-sdk`, `py_momo_sdk`, `PyMomoSDK`, `AsyncPyMomoSDK`, `PyMomoSDKConfig`, `PyMomoSDKError`, `PyMomoSDKServerError`, CLI `py-momo-sdk`, and `PY_MOMO_SDK_*`).
- Updated documentation, tests, and GitHub Pages site links to reflect `Py MoMo SDK` and `https://wkambale.github.io/pymomo/`.

## 1.0.5 - 2026-11-20

### Changed
- Redesigned the MkDocs documentation site with semantic CSS design tokens, variable `Inter` and `JetBrains Mono` typography (`cv11`, `ss01`, `text-wrap: balance`, `text-wrap: pretty`, `tabular-nums`), alternating surface bands, horizontally aligned card grids, SVG brand geometry, and an accessible icon-only scroll-to-top control.
- Refined `README.md` and all documentation pages for strict editorial hygiene: sentence case throughout, zero ampersands in prose, zero em or en dashes, zero numbered headings or cards, and clear next-action navigation links.

## 1.0.4 - 2026-11-20

### Changed
- Rebranded the project to **Py MoMo SDK** (`py-momo-sdk` on PyPI, importable package `py_momo_sdk`, CLI command `py-momo-sdk`, and `PY_MOMO_SDK_*` environment variables).
- Renamed core client, config, and exception classes to `PyMomoSDK`, `AsyncPyMomoSDK`, `PyMomoSDKConfig`, `PyMomoSDKError`, and `PyMomoSDKServerError`.
- Switched project license to MIT License (Copyright (c) 2026 Wesley Kambale) across `LICENSE`, `pyproject.toml`, and `README.md`.
- Updated all documentation, CLI help text, tests, and CI workflows to match `py_momo_sdk`, `py-momo-sdk`, and `PyMomoSDK`.

## 1.0.3 - 2026-11-20

### Changed
- Aligned package license metadata in `pyproject.toml` and `README.md`.
- Updated package metadata, README, and documentation for `py-momo-sdk` 1.0.3 and Airtel Money coverage.
- Updated `SECURITY.md` supported versions to `1.0.x`.
- Cleaned up trailing whitespace, missing EOF newlines, and non-UUID `api_user` example placeholders across documentation.

## 1.0.2 - 2026-11-20

### Added
- Collection CIBA OAuth2 token exchange (`Collection.create_oauth2_token` in sync and async clients) with secret-redacting `OAuth2TokenResponse`.
- Webhook authenticity verification helpers: constant-time `WebhookHandler.verify_hmac_signature` (SHA-256 and SHA-512) and fail-closed `WebhookHandler.verify_source_ip`.
- Public sandbox provisioner factories `create_sandbox_provisioner(subscription_key)` on sync and async clients.
- CLI `--version` / `-V` flag, `collection status <reference_id>` command, and `--base-url` option across commands.
- Dedicated Airtel Money documentation (`docs/airtel.md`) and PEP 561 `py.typed` marker.

### Changed
- Enforced strict HTTPS base URL and relative request path validation, disabled automatic HTTP redirects (`follow_redirects=False`), and validated canonical UUID v4 reference IDs, ISO currency/country codes, positive finite amounts, timeouts, callback URLs, and header control characters.
- Validated response JSON and Pydantic model parsing across all MTN MoMo and Airtel endpoints via shared `parse_model` and `parse_json_dict` helpers.
- Added thread-safe and async-safe double-checked token refresh locking with conditional cache invalidation (`expected_token`) to prevent concurrent token storms and stale invalidations.
- Enforced secret redaction across configs, models, token caches, sandbox provisioners, HTTP error chains, and CLI error handling.
- Secured GitHub Actions workflows with SHA-pinned actions, least-privilege permissions, strict Hatch sdist/wheel packaging allowlists, and full Bandit scanning without global rule skips.

### Fixed
- Fixed `AirtelTransactionResponse.is_successful()`, `is_pending()`, and `is_failed()` to evaluate `data.transaction.status` rather than outer envelope result codes, and fixed the Airtel disbursement status endpoint path (`/standard/v1/disbursements/{id}`).
- Fixed Python 3.11+ enum string interpolation for `AccountHolderIdType` path segments.
- Fixed MkDocs root configuration and updated documentation examples to use valid UUID v4 values and public APIs.

## 0.1.0 - 2026-06-15

### Added
- First public release of the client library.
- Complete Collection product client (request to pay, request to withdraw, balances, consent queries).
- Complete Disbursement product client (transfers, deposits, refunds, balances).
- Complete Remittance product client (transfers, balances).
- Standard and asynchronous client implementations.
- Sandbox API user and API key provisioning helpers.
- Typer-based command-line interface tool.
- Webhook JSON payload parse utilities.
