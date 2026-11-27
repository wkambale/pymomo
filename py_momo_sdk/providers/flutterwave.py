from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.exceptions import PyMomoSDKError
from py_momo_sdk.frameworks import verify_constant_time_token
from py_momo_sdk.http import DEFAULT_MAX_RESPONSE_BYTES, HttpClient, parse_json_dict
from py_momo_sdk.providers.models import (
    BalanceResult,
    DisbursementRequest,
    NormalizedStatus,
    PaymentRequest,
    PaymentResult,
    ProviderCapabilities,
    validate_email_address,
    validate_operation_kind,
)
from py_momo_sdk.telemetry import TelemetryHook
from py_momo_sdk.utils import (
    encode_path_segment,
    generate_reference_id,
    normalise_msisdn,
    validate_amount,
    validate_base_url,
    validate_callback_url,
    validate_currency,
    validate_header_value,
    validate_max_retries,
    validate_retry_backoff,
    validate_timeout,
)

if TYPE_CHECKING:
    from typing_extensions import Self

FLUTTERWAVE_BASE_URL = "https://api.flutterwave.com"
_VALID_FLUTTERWAVE_ENVIRONMENTS = frozenset({"sandbox", "production"})


def _is_flutterwave_live_key(secret_key: str) -> bool:
    return secret_key.startswith("FLWSECK-")


_FLUTTERWAVE_CAPABILITIES = ProviderCapabilities(
    provider_id="flutterwave",
    supports_collection=True,
    supports_disbursement=True,
    supports_balance=True,
    supports_webhook_hmac=False,
    currencies=("NGN", "GHS", "KES", "UGX", "RWF", "TZS", "ZMW", "XOF", "XAF", "USD"),
)


@dataclass
class FlutterwaveConfig:
    """Credentials and settings for Flutterwave v3 API."""

    secret_key: str
    webhook_hash: str | None = None
    redirect_url: str | None = None
    default_customer_email: str | None = None
    default_account_bank: str | None = None
    default_currency: str = "NGN"
    base_url: str = FLUTTERWAVE_BASE_URL
    timeout: float = 30.0
    max_retries: int = 0
    retry_backoff: float = 0.5
    telemetry: TelemetryHook | None = None
    environment: str | None = None

    @property
    def allow_localhost(self) -> bool:
        if self.environment == "production":
            return False
        if self.environment == "sandbox":
            return True
        return not _is_flutterwave_live_key(self.secret_key)

    def __post_init__(self) -> None:
        if not isinstance(self.secret_key, str) or not self.secret_key.strip():
            raise ValueError("secret_key must be a non-empty string")
        validate_header_value(self.secret_key, field_name="secret_key")
        if (
            self.environment is not None
            and self.environment not in _VALID_FLUTTERWAVE_ENVIRONMENTS
        ):
            raise ValueError("environment must be 'sandbox' or 'production'")
        if self.environment == "sandbox" and _is_flutterwave_live_key(self.secret_key):
            raise ValueError(
                "Live Flutterwave secret_key must not be used in sandbox environment"
            )
        if self.webhook_hash is not None:
            if not isinstance(self.webhook_hash, str) or not self.webhook_hash.strip():
                raise ValueError("webhook_hash must not be blank")
            validate_header_value(self.webhook_hash, field_name="webhook_hash")
        allow_localhost = self.allow_localhost
        if self.redirect_url is not None:
            validate_callback_url(self.redirect_url, allow_localhost=allow_localhost)
        if self.default_customer_email is not None:
            self.default_customer_email = validate_email_address(
                self.default_customer_email
            )
        if self.default_account_bank is not None:
            if not self.default_account_bank.strip():
                raise ValueError("default_account_bank must not be blank")
            self.default_account_bank = validate_header_value(
                self.default_account_bank.strip(), field_name="default_account_bank"
            )
        self.default_currency = validate_currency(self.default_currency)
        validate_base_url(self.base_url, allow_localhost=allow_localhost)
        self.timeout = validate_timeout(self.timeout)
        self.max_retries = validate_max_retries(self.max_retries)
        self.retry_backoff = validate_retry_backoff(self.retry_backoff)

    def __repr__(self) -> str:
        return (
            f"FlutterwaveConfig(secret_key=<redacted>, webhook_hash=<redacted>, "
            f"base_url={self.base_url!r}, timeout={self.timeout!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


def _map_flw_status(raw_status: str) -> NormalizedStatus:
    norm = raw_status.strip().lower()
    if norm in ("successful", "success", "completed"):
        return NormalizedStatus.SUCCEEDED
    if norm in ("reversed",):
        return NormalizedStatus.REVERSED
    if norm in ("failed", "cancelled", "canceled"):
        return NormalizedStatus.FAILED
    return NormalizedStatus.PENDING


def _validate_flw_account_number(account_number: str) -> str:
    """Validate a Flutterwave bank account, IBAN, or mobile account without stripping letters."""
    if not isinstance(account_number, str) or not account_number.strip():
        raise ValueError("account_number must be a non-empty string")
    return validate_header_value(account_number.strip(), field_name="account_number")


_FLW_MOBILE_MONEY_CHARGE_TYPE_RE = re.compile(
    r"^(mpesa|mobile_money_[a-z][a-z_]{1,30})$"
)


def _to_flw_numeric_amount(validated_amount: str) -> int | float:
    """Convert a validated decimal amount string to a JSON number for Flutterwave v3."""
    dec = Decimal(validated_amount)
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


def _validate_flw_charge_type(charge_type: str) -> str:
    if not isinstance(charge_type, str) or not charge_type.strip():
        raise ValueError("charge_type must be a non-empty string")
    cleaned = charge_type.strip().lower()
    if not _FLW_MOBILE_MONEY_CHARGE_TYPE_RE.fullmatch(cleaned):
        raise ValueError(
            "charge_type must be 'mpesa' or a valid 'mobile_money_<market>' charge type"
        )
    return cleaned


def _validate_flw_transaction_id(transaction_id: str | int) -> tuple[str, str]:
    if type(transaction_id) is bool:
        raise ValueError("transaction_id must be a non-empty string or integer")
    if isinstance(transaction_id, int):
        if transaction_id <= 0:
            raise ValueError("transaction_id must be a positive integer")
        cleaned = str(transaction_id)
    elif isinstance(transaction_id, str) and transaction_id.strip():
        cleaned = transaction_id.strip()
    else:
        raise ValueError("transaction_id must be a non-empty string or integer")
    return cleaned, encode_path_segment(cleaned, field_name="transaction_id")


def _validate_flw_meta(
    meta: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any] | list[dict[str, Any]]:
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, list) and all(isinstance(item, dict) for item in meta):
        return meta
    raise ValueError("meta must be a dict or a list of dicts")


def _encode_flw_query_ref(tx_ref: str, *, field_name: str = "tx_ref") -> str:
    if not isinstance(tx_ref, str) or not tx_ref.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    cleaned = validate_header_value(tx_ref.strip(), field_name=field_name)
    return quote(cleaned, safe="")


def _unwrap_flw_data(res: dict[str, Any]) -> dict[str, Any]:
    if str(res.get("status", "")).strip().lower() == "error":
        msg = res.get("message")
        raise PyMomoSDKError(
            str(msg) if isinstance(msg, str) and msg else "Flutterwave request failed"
        )
    data = res.get("data")
    if not isinstance(data, dict):
        raise PyMomoSDKError(
            "Malformed Flutterwave response: expected object in 'data'"
        )
    return data


def _unwrap_flw_balance(res: dict[str, Any]) -> tuple[str, str]:
    data = _unwrap_flw_data(res)
    avail = data.get("available_balance")
    currency = data.get("currency")
    if (
        avail is None
        or type(avail) is bool
        or not isinstance(currency, str)
        or not currency
    ):
        raise PyMomoSDKError("Malformed Flutterwave balance response")
    return str(avail), currency


class FlutterwaveClient:
    """Synchronous Flutterwave v3 API client."""

    def __init__(
        self,
        config: FlutterwaveConfig,
        *,
        client: httpx.Client | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        telemetry: TelemetryHook | None = None,
    ) -> None:
        self._config = config
        self._http = HttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            max_response_bytes=max_response_bytes,
            client=client,
            telemetry=telemetry if telemetry is not None else config.telemetry,
            provider_name="Flutterwave",
            allow_localhost=config.allow_localhost,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.secret_key}",
            "Content-Type": "application/json",
        }

    def create_payment(
        self,
        amount: str,
        currency: str,
        phone_number: str,
        *,
        email: str | None = None,
        tx_ref: str | None = None,
        redirect_url: str | None = None,
    ) -> dict[str, Any]:
        """Create a Flutterwave standard payment link."""
        validated_currency = validate_currency(currency)
        validated_amount = validate_amount(amount, currency=validated_currency)
        resolved_email = email or self._config.default_customer_email
        if not resolved_email:
            raise ValueError(
                "email or FlutterwaveConfig.default_customer_email is required for Flutterwave payments"
            )
        validated_email = validate_email_address(resolved_email)
        if redirect_url is not None:
            validate_callback_url(
                redirect_url, allow_localhost=self._config.allow_localhost
            )
        resolved_redirect = redirect_url or self._config.redirect_url
        ref = tx_ref or generate_reference_id()
        clean_msisdn = normalise_msisdn(phone_number)
        payload: dict[str, Any] = {
            "tx_ref": ref,
            "amount": validated_amount,
            "currency": validated_currency,
            "customer": {
                "email": validated_email,
                "phonenumber": clean_msisdn,
            },
        }
        if resolved_redirect is not None:
            payload["redirect_url"] = resolved_redirect
        response = self._http.request(
            "POST",
            "/v3/payments",
            headers=self._headers(),
            json=payload,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    def verify_by_reference(self, tx_ref: str) -> dict[str, Any]:
        """Verify a Flutterwave transaction by ``tx_ref``."""
        encoded = _encode_flw_query_ref(tx_ref)
        response = self._http.request(
            "GET",
            f"/v3/transactions/verify_by_reference?tx_ref={encoded}",
            headers=self._headers(),
            reference_id=tx_ref,
        )
        return parse_json_dict(response, reference_id=tx_ref)

    def verify_transaction_by_id(self, transaction_id: str | int) -> dict[str, Any]:
        """Verify a Flutterwave transaction by numeric transaction ID (``GET /v3/transactions/{id}/verify``)."""
        raw_id, encoded = _validate_flw_transaction_id(transaction_id)
        response = self._http.request(
            "GET",
            f"/v3/transactions/{encoded}/verify",
            headers=self._headers(),
            reference_id=raw_id,
        )
        return parse_json_dict(response, reference_id=raw_id)

    def charge_mobile_money(
        self,
        charge_type: str,
        amount: str,
        currency: str,
        phone_number: str,
        *,
        email: str | None = None,
        tx_ref: str | None = None,
        network: str | None = None,
        fullname: str | None = None,
        voucher: str | None = None,
        country: str | None = None,
        redirect_url: str | None = None,
    ) -> dict[str, Any]:
        """Initiate a direct Flutterwave Mobile Money push charge (``POST /v3/charges?type=...``)."""
        validated_type = _validate_flw_charge_type(charge_type)
        validated_currency = validate_currency(currency)
        validated_amount = validate_amount(amount, currency=validated_currency)
        resolved_email = email or self._config.default_customer_email
        if not resolved_email:
            raise ValueError(
                "email or FlutterwaveConfig.default_customer_email is required for Flutterwave charges"
            )
        validated_email = validate_email_address(resolved_email)
        if redirect_url is not None:
            validate_callback_url(
                redirect_url, allow_localhost=self._config.allow_localhost
            )
        resolved_redirect = redirect_url or self._config.redirect_url
        ref = tx_ref or generate_reference_id()
        clean_msisdn = normalise_msisdn(phone_number)
        payload: dict[str, Any] = {
            "tx_ref": ref,
            "amount": _to_flw_numeric_amount(validated_amount),
            "currency": validated_currency,
            "email": validated_email,
            "phone_number": clean_msisdn,
        }
        for key, val in (
            ("network", network),
            ("fullname", fullname),
            ("voucher", voucher),
            ("country", country),
        ):
            if val is not None:
                if not isinstance(val, str) or not val.strip():
                    raise ValueError(f"{key} must not be blank")
                payload[key] = validate_header_value(val.strip(), field_name=key)
        if resolved_redirect is not None:
            payload["redirect_url"] = resolved_redirect
        response = self._http.request(
            "POST",
            f"/v3/charges?type={validated_type}",
            headers=self._headers(),
            json=payload,
            idempotent=False,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    def refund_transaction(
        self,
        transaction_id: str | int,
        *,
        amount: str | None = None,
        comments: str | None = None,
    ) -> dict[str, Any]:
        """Refund a Flutterwave transaction (``POST /v3/transactions/{id}/refund``)."""
        raw_id, encoded = _validate_flw_transaction_id(transaction_id)
        payload: dict[str, Any] = {}
        if amount is not None:
            payload["amount"] = _to_flw_numeric_amount(validate_amount(amount))
        if comments is not None:
            if not isinstance(comments, str) or not comments.strip():
                raise ValueError("comments must not be blank")
            payload["comments"] = comments.strip()
        response = self._http.request(
            "POST",
            f"/v3/transactions/{encoded}/refund",
            headers=self._headers(),
            json=payload,
            idempotent=False,
            reference_id=raw_id,
        )
        return parse_json_dict(response, reference_id=raw_id)

    def create_transfer(
        self,
        amount: str,
        currency: str,
        account_number: str,
        *,
        account_bank: str | None = None,
        reference: str | None = None,
        narration: str = "Payout",
        callback_url: str | None = None,
        beneficiary_name: str | None = None,
        destination_branch_code: str | None = None,
        debit_currency: str | None = None,
        meta: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Initiate a Flutterwave transfer."""
        validated_currency = validate_currency(currency)
        validated_amount = validate_amount(amount, currency=validated_currency)
        resolved_bank = account_bank or self._config.default_account_bank
        if not resolved_bank or not resolved_bank.strip():
            raise ValueError(
                "account_bank or FlutterwaveConfig.default_account_bank is required for Flutterwave transfers"
            )
        validated_bank = validate_header_value(
            resolved_bank.strip(), field_name="account_bank"
        )
        validated_account = _validate_flw_account_number(account_number)
        if callback_url is not None:
            validate_callback_url(
                callback_url, allow_localhost=self._config.allow_localhost
            )
        ref = reference or generate_reference_id()
        payload: dict[str, Any] = {
            "account_bank": validated_bank,
            "account_number": validated_account,
            "amount": _to_flw_numeric_amount(validated_amount),
            "currency": validated_currency,
            "narration": narration,
            "reference": ref,
        }
        if callback_url is not None:
            payload["callback_url"] = callback_url
        if beneficiary_name is not None:
            if not isinstance(beneficiary_name, str) or not beneficiary_name.strip():
                raise ValueError("beneficiary_name must not be blank")
            payload["beneficiary_name"] = validate_header_value(
                beneficiary_name.strip(), field_name="beneficiary_name"
            )
        if destination_branch_code is not None:
            if (
                not isinstance(destination_branch_code, str)
                or not destination_branch_code.strip()
            ):
                raise ValueError("destination_branch_code must not be blank")
            payload["destination_branch_code"] = validate_header_value(
                destination_branch_code.strip(), field_name="destination_branch_code"
            )
        if debit_currency is not None:
            payload["debit_currency"] = validate_currency(debit_currency)
        if meta is not None:
            payload["meta"] = _validate_flw_meta(meta)
        response = self._http.request(
            "POST",
            "/v3/transfers",
            headers=self._headers(),
            json=payload,
            idempotent=False,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    def get_transfer(self, transfer_id: str) -> dict[str, Any]:
        """Retrieve a Flutterwave transfer by ID."""
        encoded = encode_path_segment(transfer_id, field_name="transfer_id")
        response = self._http.request(
            "GET",
            f"/v3/transfers/{encoded}",
            headers=self._headers(),
            reference_id=transfer_id,
        )
        return parse_json_dict(response, reference_id=transfer_id)

    def get_transfer_by_reference(self, reference: str) -> dict[str, Any]:
        """Reconcile a Flutterwave transfer by merchant reference (``GET /v3/transfers?reference=...``)."""
        encoded = _encode_flw_query_ref(reference, field_name="reference")
        response = self._http.request(
            "GET",
            f"/v3/transfers?reference={encoded}",
            headers=self._headers(),
            reference_id=reference,
        )
        return parse_json_dict(response, reference_id=reference)

    def get_balance(self, currency: str | None = None) -> dict[str, Any]:
        """Retrieve Flutterwave wallet balance for a currency."""
        iso = validate_currency(currency or self._config.default_currency)
        response = self._http.request(
            "GET", f"/v3/balances/{iso}", headers=self._headers()
        )
        return parse_json_dict(response)

    def verify_webhook_hash(self, verif_hash: str) -> None:
        """Verify Flutterwave's ``verif-hash`` header in constant time."""
        verify_constant_time_token(verif_hash, self._config.webhook_hash or "")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncFlutterwaveClient:
    """Asynchronous Flutterwave v3 API client."""

    def __init__(
        self,
        config: FlutterwaveConfig,
        *,
        client: httpx.AsyncClient | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        telemetry: TelemetryHook | None = None,
    ) -> None:
        self._config = config
        self._http = AsyncHttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            max_response_bytes=max_response_bytes,
            client=client,
            telemetry=telemetry if telemetry is not None else config.telemetry,
            provider_name="Flutterwave",
            allow_localhost=config.allow_localhost,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.secret_key}",
            "Content-Type": "application/json",
        }

    async def create_payment(
        self,
        amount: str,
        currency: str,
        phone_number: str,
        *,
        email: str | None = None,
        tx_ref: str | None = None,
        redirect_url: str | None = None,
    ) -> dict[str, Any]:
        validated_currency = validate_currency(currency)
        validated_amount = validate_amount(amount, currency=validated_currency)
        resolved_email = email or self._config.default_customer_email
        if not resolved_email:
            raise ValueError(
                "email or FlutterwaveConfig.default_customer_email is required for Flutterwave payments"
            )
        validated_email = validate_email_address(resolved_email)
        if redirect_url is not None:
            validate_callback_url(
                redirect_url, allow_localhost=self._config.allow_localhost
            )
        resolved_redirect = redirect_url or self._config.redirect_url
        ref = tx_ref or generate_reference_id()
        clean_msisdn = normalise_msisdn(phone_number)
        payload: dict[str, Any] = {
            "tx_ref": ref,
            "amount": validated_amount,
            "currency": validated_currency,
            "customer": {
                "email": validated_email,
                "phonenumber": clean_msisdn,
            },
        }
        if resolved_redirect is not None:
            payload["redirect_url"] = resolved_redirect
        response = await self._http.request(
            "POST",
            "/v3/payments",
            headers=self._headers(),
            json=payload,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    async def verify_by_reference(self, tx_ref: str) -> dict[str, Any]:
        encoded = _encode_flw_query_ref(tx_ref)
        response = await self._http.request(
            "GET",
            f"/v3/transactions/verify_by_reference?tx_ref={encoded}",
            headers=self._headers(),
            reference_id=tx_ref,
        )
        return parse_json_dict(response, reference_id=tx_ref)

    async def verify_transaction_by_id(
        self, transaction_id: str | int
    ) -> dict[str, Any]:
        """Verify a Flutterwave transaction by numeric transaction ID asynchronously."""
        raw_id, encoded = _validate_flw_transaction_id(transaction_id)
        response = await self._http.request(
            "GET",
            f"/v3/transactions/{encoded}/verify",
            headers=self._headers(),
            reference_id=raw_id,
        )
        return parse_json_dict(response, reference_id=raw_id)

    async def charge_mobile_money(
        self,
        charge_type: str,
        amount: str,
        currency: str,
        phone_number: str,
        *,
        email: str | None = None,
        tx_ref: str | None = None,
        network: str | None = None,
        fullname: str | None = None,
        voucher: str | None = None,
        country: str | None = None,
        redirect_url: str | None = None,
    ) -> dict[str, Any]:
        """Initiate a direct Flutterwave Mobile Money push charge asynchronously."""
        validated_type = _validate_flw_charge_type(charge_type)
        validated_currency = validate_currency(currency)
        validated_amount = validate_amount(amount, currency=validated_currency)
        resolved_email = email or self._config.default_customer_email
        if not resolved_email:
            raise ValueError(
                "email or FlutterwaveConfig.default_customer_email is required for Flutterwave charges"
            )
        validated_email = validate_email_address(resolved_email)
        if redirect_url is not None:
            validate_callback_url(
                redirect_url, allow_localhost=self._config.allow_localhost
            )
        resolved_redirect = redirect_url or self._config.redirect_url
        ref = tx_ref or generate_reference_id()
        clean_msisdn = normalise_msisdn(phone_number)
        payload: dict[str, Any] = {
            "tx_ref": ref,
            "amount": _to_flw_numeric_amount(validated_amount),
            "currency": validated_currency,
            "email": validated_email,
            "phone_number": clean_msisdn,
        }
        for key, val in (
            ("network", network),
            ("fullname", fullname),
            ("voucher", voucher),
            ("country", country),
        ):
            if val is not None:
                if not isinstance(val, str) or not val.strip():
                    raise ValueError(f"{key} must not be blank")
                payload[key] = validate_header_value(val.strip(), field_name=key)
        if resolved_redirect is not None:
            payload["redirect_url"] = resolved_redirect
        response = await self._http.request(
            "POST",
            f"/v3/charges?type={validated_type}",
            headers=self._headers(),
            json=payload,
            idempotent=False,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    async def refund_transaction(
        self,
        transaction_id: str | int,
        *,
        amount: str | None = None,
        comments: str | None = None,
    ) -> dict[str, Any]:
        """Refund a Flutterwave transaction asynchronously."""
        raw_id, encoded = _validate_flw_transaction_id(transaction_id)
        payload: dict[str, Any] = {}
        if amount is not None:
            payload["amount"] = _to_flw_numeric_amount(validate_amount(amount))
        if comments is not None:
            if not isinstance(comments, str) or not comments.strip():
                raise ValueError("comments must not be blank")
            payload["comments"] = comments.strip()
        response = await self._http.request(
            "POST",
            f"/v3/transactions/{encoded}/refund",
            headers=self._headers(),
            json=payload,
            idempotent=False,
            reference_id=raw_id,
        )
        return parse_json_dict(response, reference_id=raw_id)

    async def create_transfer(
        self,
        amount: str,
        currency: str,
        account_number: str,
        *,
        account_bank: str | None = None,
        reference: str | None = None,
        narration: str = "Payout",
        callback_url: str | None = None,
        beneficiary_name: str | None = None,
        destination_branch_code: str | None = None,
        debit_currency: str | None = None,
        meta: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        validated_currency = validate_currency(currency)
        validated_amount = validate_amount(amount, currency=validated_currency)
        resolved_bank = account_bank or self._config.default_account_bank
        if not resolved_bank or not resolved_bank.strip():
            raise ValueError(
                "account_bank or FlutterwaveConfig.default_account_bank is required for Flutterwave transfers"
            )
        validated_bank = validate_header_value(
            resolved_bank.strip(), field_name="account_bank"
        )
        validated_account = _validate_flw_account_number(account_number)
        if callback_url is not None:
            validate_callback_url(
                callback_url, allow_localhost=self._config.allow_localhost
            )
        ref = reference or generate_reference_id()
        payload: dict[str, Any] = {
            "account_bank": validated_bank,
            "account_number": validated_account,
            "amount": _to_flw_numeric_amount(validated_amount),
            "currency": validated_currency,
            "narration": narration,
            "reference": ref,
        }
        if callback_url is not None:
            payload["callback_url"] = callback_url
        if beneficiary_name is not None:
            if not isinstance(beneficiary_name, str) or not beneficiary_name.strip():
                raise ValueError("beneficiary_name must not be blank")
            payload["beneficiary_name"] = validate_header_value(
                beneficiary_name.strip(), field_name="beneficiary_name"
            )
        if destination_branch_code is not None:
            if (
                not isinstance(destination_branch_code, str)
                or not destination_branch_code.strip()
            ):
                raise ValueError("destination_branch_code must not be blank")
            payload["destination_branch_code"] = validate_header_value(
                destination_branch_code.strip(), field_name="destination_branch_code"
            )
        if debit_currency is not None:
            payload["debit_currency"] = validate_currency(debit_currency)
        if meta is not None:
            payload["meta"] = _validate_flw_meta(meta)
        response = await self._http.request(
            "POST",
            "/v3/transfers",
            headers=self._headers(),
            json=payload,
            idempotent=False,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    async def get_transfer(self, transfer_id: str) -> dict[str, Any]:
        encoded = encode_path_segment(transfer_id, field_name="transfer_id")
        response = await self._http.request(
            "GET",
            f"/v3/transfers/{encoded}",
            headers=self._headers(),
            reference_id=transfer_id,
        )
        return parse_json_dict(response, reference_id=transfer_id)

    async def get_transfer_by_reference(self, reference: str) -> dict[str, Any]:
        """Reconcile a Flutterwave transfer by merchant reference asynchronously."""
        encoded = _encode_flw_query_ref(reference, field_name="reference")
        response = await self._http.request(
            "GET",
            f"/v3/transfers?reference={encoded}",
            headers=self._headers(),
            reference_id=reference,
        )
        return parse_json_dict(response, reference_id=reference)

    async def get_balance(self, currency: str | None = None) -> dict[str, Any]:
        iso = validate_currency(currency or self._config.default_currency)
        response = await self._http.request(
            "GET", f"/v3/balances/{iso}", headers=self._headers()
        )
        return parse_json_dict(response)

    def verify_webhook_hash(self, verif_hash: str) -> None:
        """Verify Flutterwave's ``verif-hash`` header in constant time."""
        verify_constant_time_token(verif_hash, self._config.webhook_hash or "")

    async def close(self) -> None:
        await self._http.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


def _map_flw_status_response(
    provider: str, reference_id: str, res: dict[str, Any]
) -> PaymentResult:
    data = _unwrap_flw_data(res)
    amount = str(data["amount"]) if data.get("amount") is not None else None
    tx_id = str(data["id"]) if data.get("id") is not None else None
    reason_val = data.get("complete_message") or data.get("processor_response")
    reason = str(reason_val) if isinstance(reason_val, str) and reason_val else None
    return PaymentResult(
        provider=provider,
        reference_id=reference_id,
        status=_map_flw_status(str(data.get("status", "pending"))),
        amount=amount,
        currency=data.get("currency"),
        provider_transaction_id=tx_id,
        reason=reason,
        raw=res,
    )


class FlutterwaveProvider:
    """Synchronous unified provider adapter for Flutterwave."""

    def __init__(self, client: FlutterwaveClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "flutterwave"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _FLUTTERWAVE_CAPABILITIES

    def collect(self, request: PaymentRequest) -> PaymentResult:
        ref = request.reference_id or generate_reference_id()
        res = self._client.create_payment(
            amount=request.amount,
            currency=request.currency,
            phone_number=request.payer_msisdn,
            email=request.payer_email,
            tx_ref=ref,
            redirect_url=request.callback_url,
        )
        data = _unwrap_flw_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or ref,
            checkout_url=data.get("link"),
            raw=res,
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        ref = request.reference_id or generate_reference_id()
        res = self._client.create_transfer(
            amount=request.amount,
            currency=request.currency,
            account_number=request.payee_msisdn,
            account_bank=request.payee_bank_code,
            reference=ref,
            narration=request.payer_message or "Payout",
            callback_url=request.callback_url,
        )
        data = _unwrap_flw_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("id") or data.get("reference") or ref),
            status=_map_flw_status(str(data.get("status", "pending"))),
            amount=request.amount,
            currency=request.currency,
            external_id=str(data.get("reference") or ref),
            raw=res,
        )

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        res = (
            self._client.get_transfer(reference_id)
            if kind == "disbursement"
            else self._client.verify_by_reference(reference_id)
        )
        return _map_flw_status_response(self.name, reference_id, res)

    def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        validate_operation_kind(kind)
        res = self._client.get_balance(currency=currency)
        avail, resolved_currency = _unwrap_flw_balance(res)
        return BalanceResult(
            provider=self.name,
            available_balance=avail,
            currency=resolved_currency,
            raw=res,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncFlutterwaveProvider:
    """Asynchronous unified provider adapter for Flutterwave."""

    def __init__(self, client: AsyncFlutterwaveClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "flutterwave"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _FLUTTERWAVE_CAPABILITIES

    async def collect(self, request: PaymentRequest) -> PaymentResult:
        ref = request.reference_id or generate_reference_id()
        res = await self._client.create_payment(
            amount=request.amount,
            currency=request.currency,
            phone_number=request.payer_msisdn,
            email=request.payer_email,
            tx_ref=ref,
            redirect_url=request.callback_url,
        )
        data = _unwrap_flw_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or ref,
            checkout_url=data.get("link"),
            raw=res,
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        ref = request.reference_id or generate_reference_id()
        res = await self._client.create_transfer(
            amount=request.amount,
            currency=request.currency,
            account_number=request.payee_msisdn,
            account_bank=request.payee_bank_code,
            reference=ref,
            narration=request.payer_message or "Payout",
            callback_url=request.callback_url,
        )
        data = _unwrap_flw_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("id") or data.get("reference") or ref),
            status=_map_flw_status(str(data.get("status", "pending"))),
            amount=request.amount,
            currency=request.currency,
            external_id=str(data.get("reference") or ref),
            raw=res,
        )

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        res = (
            await self._client.get_transfer(reference_id)
            if kind == "disbursement"
            else await self._client.verify_by_reference(reference_id)
        )
        return _map_flw_status_response(self.name, reference_id, res)

    async def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        validate_operation_kind(kind)
        res = await self._client.get_balance(currency=currency)
        avail, resolved_currency = _unwrap_flw_balance(res)
        return BalanceResult(
            provider=self.name,
            available_balance=avail,
            currency=resolved_currency,
            raw=res,
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def close(self) -> None:
        await self.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
