# Changelog

All notable changes to the Py MoMo API (`py-momo-api`) project will be documented in this file.

## 1.0.4 - 2026-11-20

### Changed
- Rebranded the project to **Py MoMo API** (`py-momo-api` on PyPI, importable package `py_momo_api`, CLI command `py-momo-api`, and `PY_MOMO_API_*` environment variables).
- Renamed core client, config, and exception classes to `PyMomoAPI`, `AsyncPyMomoAPI`, `PyMomoAPIConfig`, `PyMomoAPIError`, and `PyMomoAPIServerError`.
- Switched project license to MIT License (Copyright (c) 2026 Wesley Kambale) across `LICENSE`, `pyproject.toml`, and `README.md`.
- Updated all documentation, CLI help text, tests, and CI workflows to match `py_momo_api`, `py-momo-api`, and `PyMomoAPI`.

## 1.0.3 - 2026-11-20

### Changed
- Aligned package license metadata in `pyproject.toml` and `README.md`.
- Updated package metadata, README, and documentation for `py-momo-api` 1.0.3 and Airtel Money coverage.
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
- Hardened response JSON and Pydantic model parsing across all MTN MoMo and Airtel endpoints via shared `parse_model` and `parse_json_dict` helpers.
- Added thread-safe and async-safe double-checked token refresh locking with conditional cache invalidation (`expected_token`) to prevent concurrent token storms and stale invalidations.
- Hardened secret redaction across configs, models, token caches, sandbox provisioners, HTTP error chains, and CLI error handling.
- Hardened GitHub Actions workflows with SHA-pinned actions, least-privilege permissions, strict Hatch sdist/wheel packaging allowlists, and full Bandit scanning without global rule skips.

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
