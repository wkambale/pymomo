from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.exceptions import PyMomoSDKError
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
    _ZERO_DECIMAL_CURRENCIES,
    encode_path_segment,
    generate_reference_id,
    validate_amount,
    validate_base_url,
    validate_callback_url,
    validate_currency,
    validate_header_value,
    validate_max_retries,
    validate_retry_backoff,
    validate_timeout,
)
from py_momo_sdk.webhooks import WebhookHandler

if TYPE_CHECKING:
    from typing_extensions import Self

PAYSTACK_BASE_URL = "https://api.paystack.co"
_VALID_PAYSTACK_ENVIRONMENTS = frozenset({"sandbox", "production"})


def _is_paystack_live_key(secret_key: str) -> bool:
    return secret_key.startswith("sk_live_")


_PAYSTACK_CAPABILITIES = ProviderCapabilities(
    provider_id="paystack",
    supports_collection=True,
    supports_disbursement=True,
    supports_balance=True,
    supports_webhook_hmac=True,
    currencies=("NGN", "GHS", "KES", "ZAR", "XOF", "USD"),
)


_PAYSTACK_ZERO_DECIMAL_CURRENCIES = _ZERO_DECIMAL_CURRENCIES


@dataclass
class PaystackConfig:
    """Credentials and settings for Paystack API."""

    secret_key: str
    callback_url: str | None = None
    default_customer_email: str | None = None
    default_currency: str | None = None
    base_url: str = PAYSTACK_BASE_URL
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
        return not _is_paystack_live_key(self.secret_key)

    def __post_init__(self) -> None:
        if not isinstance(self.secret_key, str) or not self.secret_key.strip():
            raise ValueError("secret_key must be a non-empty string")
        self.secret_key = validate_header_value(
            self.secret_key.strip(), field_name="secret_key"
        )
        if (
            self.environment is not None
            and self.environment not in _VALID_PAYSTACK_ENVIRONMENTS
        ):
            raise ValueError("environment must be 'sandbox' or 'production'")
        if self.environment == "sandbox" and _is_paystack_live_key(self.secret_key):
            raise ValueError(
                "Live Paystack secret_key must not be used in sandbox environment"
            )
        allow_localhost = self.allow_localhost
        if self.callback_url is not None:
            validate_callback_url(self.callback_url, allow_localhost=allow_localhost)
        if self.default_customer_email is not None:
            self.default_customer_email = validate_email_address(
                self.default_customer_email
            )
        if self.default_currency is not None:
            self.default_currency = validate_currency(self.default_currency)
        validate_base_url(self.base_url, allow_localhost=allow_localhost)
        self.timeout = validate_timeout(self.timeout)
        self.max_retries = validate_max_retries(self.max_retries)
        self.retry_backoff = validate_retry_backoff(self.retry_backoff)

    def __repr__(self) -> str:
        return (
            f"PaystackConfig(secret_key=<redacted>, "
            f"base_url={self.base_url!r}, timeout={self.timeout!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


def _to_minor_units(amount: str, currency: str | None = None) -> int:
    validated = validate_amount(amount)
    dec = Decimal(validated)
    if (
        currency is not None
        and currency.strip().upper() in _PAYSTACK_ZERO_DECIMAL_CURRENCIES
        and dec != dec.to_integral_value()
    ):
        raise ValueError(
            f"Currency {currency.strip().upper()} does not support fractional minor units"
        )
    scaled = dec * Decimal(100)
    if scaled != scaled.to_integral_value():
        raise ValueError(
            "Amount cannot have more than 2 decimal places for minor-unit conversion"
        )
    return int(scaled)


def _from_minor_units(minor: object) -> str:
    if type(minor) is bool or not isinstance(minor, (int, str)):
        raise PyMomoSDKError("Malformed Paystack minor-unit amount")
    try:
        dec = (Decimal(str(minor)) / Decimal(100)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise PyMomoSDKError("Malformed Paystack minor-unit amount") from exc
    return format(dec, "f")


def _unwrap_paystack_data(res: dict[str, Any]) -> dict[str, Any]:
    if res.get("status") is False:
        msg = res.get("message")
        raise PyMomoSDKError(
            str(msg) if isinstance(msg, str) and msg else "Paystack request failed"
        )
    data = res.get("data")
    if not isinstance(data, dict):
        raise PyMomoSDKError("Malformed Paystack response: expected object in 'data'")
    return data


def _unwrap_paystack_balance(
    res: dict[str, Any], *, currency: str | None = None
) -> tuple[str, str]:
    if res.get("status") is False:
        msg = res.get("message")
        raise PyMomoSDKError(
            str(msg) if isinstance(msg, str) and msg else "Paystack request failed"
        )
    items = res.get("data")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise PyMomoSDKError("Malformed Paystack balance response")
    target = validate_currency(currency) if currency is not None else None
    selected: dict[str, Any] | None = None
    if target is not None:
        for item in items:
            if (
                isinstance(item, dict)
                and isinstance(item.get("currency"), str)
                and item["currency"].strip().upper() == target
            ):
                selected = item
                break
        if selected is None:
            raise PyMomoSDKError(f"Paystack balance for currency {target!r} not found")
    else:
        selected = items[0]
    if (
        "balance" not in selected
        or not isinstance(selected.get("currency"), str)
        or not selected["currency"]
    ):
        raise PyMomoSDKError("Malformed Paystack balance response")
    return _from_minor_units(selected["balance"]), selected["currency"]


def _map_paystack_status(raw_status: str) -> NormalizedStatus:
    norm = raw_status.strip().lower()
    if norm in ("success", "succeeded"):
        return NormalizedStatus.SUCCEEDED
    if norm in ("failed", "abandoned", "rejected", "blocked"):
        return NormalizedStatus.FAILED
    if norm in ("reversed",):
        return NormalizedStatus.REVERSED
    return NormalizedStatus.PENDING


_PAYSTACK_TRANSFER_REF_RE = re.compile(r"^[a-z0-9_-]{16,50}$")


def _validate_paystack_reference(reference: str | None) -> str:
    if reference is None:
        return generate_reference_id()
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("reference must be a non-empty string")
    cleaned = reference.strip()
    encode_path_segment(cleaned, field_name="reference")
    return cleaned


def _validate_paystack_transfer_reference(reference: str | None) -> str:
    if reference is None:
        return generate_reference_id()
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("reference must be a non-empty string")
    cleaned = reference.strip()
    if not _PAYSTACK_TRANSFER_REF_RE.fullmatch(cleaned):
        raise ValueError(
            "Paystack transfer reference must be 16-50 lowercase characters matching [a-z0-9_-]"
        )
    return cleaned


def _validate_paystack_channels(channels: Sequence[str]) -> list[str]:
    if isinstance(channels, (str, bytes)) or not channels:
        raise ValueError("channels must be a non-empty sequence of channel strings")
    cleaned_channels: list[str] = []
    for ch in channels:
        if not isinstance(ch, str) or not ch.strip():
            raise ValueError("each Paystack channel must be a non-empty string")
        cleaned_channels.append(validate_header_value(ch.strip(), field_name="channel"))
    return cleaned_channels


def _map_paystack_status_response(
    provider: str, reference_id: str, res: dict[str, Any]
) -> PaymentResult:
    data = _unwrap_paystack_data(res)
    amount = (
        _from_minor_units(data["amount"]) if data.get("amount") is not None else None
    )
    tx_id = str(data["id"]) if data.get("id") is not None else None
    reason_val = data.get("gateway_response") or data.get("reason")
    reason = str(reason_val) if isinstance(reason_val, str) and reason_val else None
    return PaymentResult(
        provider=provider,
        reference_id=reference_id,
        status=_map_paystack_status(str(data.get("status", "pending"))),
        amount=amount,
        currency=data.get("currency"),
        provider_transaction_id=tx_id,
        reason=reason,
        raw=res,
    )


class PaystackClient:
    """Synchronous Paystack API client."""

    def __init__(
        self,
        config: PaystackConfig,
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
            provider_name="Paystack",
            allow_localhost=config.allow_localhost,
        )

    @property
    def default_customer_email(self) -> str | None:
        return self._config.default_customer_email

    @property
    def default_currency(self) -> str | None:
        return self._config.default_currency

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.secret_key}",
            "Content-Type": "application/json",
        }

    def initialize_transaction(
        self,
        email: str,
        amount: str,
        currency: str,
        *,
        reference: str | None = None,
        callback_url: str | None = None,
        channels: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Initialize a Paystack transaction (amounts converted to minor units)."""
        validated_email = validate_email_address(email)
        validated_currency = validate_currency(currency)
        minor_amount = _to_minor_units(amount, currency=validated_currency)
        if callback_url is not None:
            validate_callback_url(
                callback_url, allow_localhost=self._config.allow_localhost
            )
        resolved_cb = callback_url or self._config.callback_url
        ref = _validate_paystack_reference(reference)
        payload: dict[str, Any] = {
            "email": validated_email,
            "amount": minor_amount,
            "currency": validated_currency,
            "reference": ref,
        }
        if resolved_cb is not None:
            payload["callback_url"] = resolved_cb
        if channels is not None:
            payload["channels"] = _validate_paystack_channels(channels)
        response = self._http.request(
            "POST",
            "/transaction/initialize",
            headers=self._headers(),
            json=payload,
            idempotent=False,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    def verify_transaction(self, reference: str) -> dict[str, Any]:
        """Verify a Paystack transaction by reference."""
        encoded = encode_path_segment(reference, field_name="reference")
        response = self._http.request(
            "GET",
            f"/transaction/verify/{encoded}",
            headers=self._headers(),
            reference_id=reference,
        )
        return parse_json_dict(response, reference_id=reference)

    def initiate_transfer(
        self,
        amount: str,
        currency: str,
        recipient: str,
        *,
        reference: str | None = None,
        reason: str = "Payout",
    ) -> dict[str, Any]:
        """Initiate a Paystack transfer to a recipient code."""
        validated_currency = validate_currency(currency)
        minor_amount = _to_minor_units(amount, currency=validated_currency)
        if not isinstance(recipient, str) or not recipient.strip():
            raise ValueError("recipient must be a non-empty recipient code")
        validate_header_value(recipient.strip(), field_name="recipient")
        ref = _validate_paystack_transfer_reference(reference)
        response = self._http.request(
            "POST",
            "/transfer",
            headers=self._headers(),
            json={
                "source": "balance",
                "amount": minor_amount,
                "currency": validated_currency,
                "recipient": recipient.strip(),
                "reference": ref,
                "reason": reason,
            },
            idempotent=False,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    def create_transfer_recipient(
        self,
        recipient_type: str,
        name: str,
        account_number: str,
        bank_code: str,
        currency: str,
        *,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a Paystack transfer recipient (``POST /transferrecipient``)."""
        for fname, fval in (
            ("recipient_type", recipient_type),
            ("name", name),
            ("account_number", account_number),
            ("bank_code", bank_code),
        ):
            if not isinstance(fval, str) or not fval.strip():
                raise ValueError(f"{fname} must be a non-empty string")
            validate_header_value(fval.strip(), field_name=fname)
        validated_currency = validate_currency(currency)
        payload: dict[str, Any] = {
            "type": recipient_type.strip(),
            "name": name.strip(),
            "account_number": account_number.strip(),
            "bank_code": bank_code.strip(),
            "currency": validated_currency,
        }
        if description is not None:
            payload["description"] = description
        response = self._http.request(
            "POST",
            "/transferrecipient",
            headers=self._headers(),
            json=payload,
        )
        return parse_json_dict(response)

    def list_banks(
        self,
        *,
        country: str | None = None,
        currency: str | None = None,
        bank_type: str | None = None,
    ) -> dict[str, Any]:
        """List Paystack supported banks and mobile money operators (``GET /bank``)."""
        params: dict[str, str] = {}
        if country is not None:
            params["country"] = validate_header_value(
                country.strip(), field_name="country"
            )
        if currency is not None:
            params["currency"] = validate_currency(currency)
        if bank_type is not None:
            params["type"] = validate_header_value(
                bank_type.strip(), field_name="bank_type"
            )
        path = f"/bank?{urlencode(params)}" if params else "/bank"
        response = self._http.request("GET", path, headers=self._headers())
        return parse_json_dict(response)

    def charge_mobile_money(
        self,
        email: str,
        amount: str,
        currency: str,
        phone: str,
        provider: str,
        *,
        reference: str | None = None,
    ) -> dict[str, Any]:
        """Initiate a direct Paystack mobile money charge (``POST /charge``)."""
        validated_email = validate_email_address(email)
        validated_currency = validate_currency(currency)
        minor_amount = _to_minor_units(amount, currency=validated_currency)
        if not isinstance(phone, str) or not phone.strip():
            raise ValueError("phone must be a non-empty string")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be a non-empty string")
        ref = _validate_paystack_reference(reference)
        response = self._http.request(
            "POST",
            "/charge",
            headers=self._headers(),
            json={
                "email": validated_email,
                "amount": minor_amount,
                "currency": validated_currency,
                "reference": ref,
                "mobile_money": {
                    "phone": validate_header_value(phone.strip(), field_name="phone"),
                    "provider": validate_header_value(
                        provider.strip().lower(), field_name="provider"
                    ),
                },
            },
            idempotent=False,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    def create_refund(
        self,
        transaction: str,
        *,
        amount: str | None = None,
        currency: str | None = None,
        customer_note: str | None = None,
        merchant_note: str | None = None,
    ) -> dict[str, Any]:
        """Create a Paystack refund (``POST /refund``)."""
        if not isinstance(transaction, str) or not transaction.strip():
            raise ValueError("transaction must be a non-empty string")
        tx_ref = validate_header_value(transaction.strip(), field_name="transaction")
        payload: dict[str, Any] = {"transaction": tx_ref}
        validated_currency = (
            validate_currency(currency) if currency is not None else None
        )
        if validated_currency is not None:
            payload["currency"] = validated_currency
        if amount is not None:
            payload["amount"] = _to_minor_units(amount, currency=validated_currency)
        if customer_note is not None:
            payload["customer_note"] = customer_note
        if merchant_note is not None:
            payload["merchant_note"] = merchant_note
        response = self._http.request(
            "POST",
            "/refund",
            headers=self._headers(),
            json=payload,
            idempotent=False,
            reference_id=tx_ref,
        )
        return parse_json_dict(response, reference_id=tx_ref)

    def verify_transfer(self, reference: str) -> dict[str, Any]:
        """Verify a Paystack transfer by reference."""
        encoded = encode_path_segment(reference, field_name="reference")
        response = self._http.request(
            "GET",
            f"/transfer/verify/{encoded}",
            headers=self._headers(),
            reference_id=reference,
        )
        return parse_json_dict(response, reference_id=reference)

    def get_balance(self) -> dict[str, Any]:
        """Retrieve Paystack account balances."""
        response = self._http.request("GET", "/balance", headers=self._headers())
        return parse_json_dict(response)

    def verify_webhook(self, payload: bytes, signature: str) -> None:
        """Verify ``x-paystack-signature`` HMAC-SHA512 header against raw bytes."""
        WebhookHandler.verify_hmac_signature(
            payload, signature, self._config.secret_key, algorithm="sha512"
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncPaystackClient:
    """Asynchronous Paystack API client."""

    def __init__(
        self,
        config: PaystackConfig,
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
            provider_name="Paystack",
            allow_localhost=config.allow_localhost,
        )

    @property
    def default_customer_email(self) -> str | None:
        return self._config.default_customer_email

    @property
    def default_currency(self) -> str | None:
        return self._config.default_currency

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.secret_key}",
            "Content-Type": "application/json",
        }

    async def initialize_transaction(
        self,
        email: str,
        amount: str,
        currency: str,
        *,
        reference: str | None = None,
        callback_url: str | None = None,
        channels: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        validated_email = validate_email_address(email)
        validated_currency = validate_currency(currency)
        minor_amount = _to_minor_units(amount, currency=validated_currency)
        if callback_url is not None:
            validate_callback_url(
                callback_url, allow_localhost=self._config.allow_localhost
            )
        resolved_cb = callback_url or self._config.callback_url
        ref = _validate_paystack_reference(reference)
        payload: dict[str, Any] = {
            "email": validated_email,
            "amount": minor_amount,
            "currency": validated_currency,
            "reference": ref,
        }
        if resolved_cb is not None:
            payload["callback_url"] = resolved_cb
        if channels is not None:
            payload["channels"] = _validate_paystack_channels(channels)
        response = await self._http.request(
            "POST",
            "/transaction/initialize",
            headers=self._headers(),
            json=payload,
            idempotent=False,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    async def verify_transaction(self, reference: str) -> dict[str, Any]:
        encoded = encode_path_segment(reference, field_name="reference")
        response = await self._http.request(
            "GET",
            f"/transaction/verify/{encoded}",
            headers=self._headers(),
            reference_id=reference,
        )
        return parse_json_dict(response, reference_id=reference)

    async def initiate_transfer(
        self,
        amount: str,
        currency: str,
        recipient: str,
        *,
        reference: str | None = None,
        reason: str = "Payout",
    ) -> dict[str, Any]:
        validated_currency = validate_currency(currency)
        minor_amount = _to_minor_units(amount, currency=validated_currency)
        if not isinstance(recipient, str) or not recipient.strip():
            raise ValueError("recipient must be a non-empty recipient code")
        validate_header_value(recipient.strip(), field_name="recipient")
        ref = _validate_paystack_transfer_reference(reference)
        response = await self._http.request(
            "POST",
            "/transfer",
            headers=self._headers(),
            json={
                "source": "balance",
                "amount": minor_amount,
                "currency": validated_currency,
                "recipient": recipient.strip(),
                "reference": ref,
                "reason": reason,
            },
            idempotent=False,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    async def create_transfer_recipient(
        self,
        recipient_type: str,
        name: str,
        account_number: str,
        bank_code: str,
        currency: str,
        *,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a Paystack transfer recipient asynchronously."""
        for fname, fval in (
            ("recipient_type", recipient_type),
            ("name", name),
            ("account_number", account_number),
            ("bank_code", bank_code),
        ):
            if not isinstance(fval, str) or not fval.strip():
                raise ValueError(f"{fname} must be a non-empty string")
            validate_header_value(fval.strip(), field_name=fname)
        validated_currency = validate_currency(currency)
        payload: dict[str, Any] = {
            "type": recipient_type.strip(),
            "name": name.strip(),
            "account_number": account_number.strip(),
            "bank_code": bank_code.strip(),
            "currency": validated_currency,
        }
        if description is not None:
            payload["description"] = description
        response = await self._http.request(
            "POST",
            "/transferrecipient",
            headers=self._headers(),
            json=payload,
        )
        return parse_json_dict(response)

    async def list_banks(
        self,
        *,
        country: str | None = None,
        currency: str | None = None,
        bank_type: str | None = None,
    ) -> dict[str, Any]:
        """List Paystack supported banks and mobile money operators asynchronously."""
        params: dict[str, str] = {}
        if country is not None:
            params["country"] = validate_header_value(
                country.strip(), field_name="country"
            )
        if currency is not None:
            params["currency"] = validate_currency(currency)
        if bank_type is not None:
            params["type"] = validate_header_value(
                bank_type.strip(), field_name="bank_type"
            )
        path = f"/bank?{urlencode(params)}" if params else "/bank"
        response = await self._http.request("GET", path, headers=self._headers())
        return parse_json_dict(response)

    async def charge_mobile_money(
        self,
        email: str,
        amount: str,
        currency: str,
        phone: str,
        provider: str,
        *,
        reference: str | None = None,
    ) -> dict[str, Any]:
        """Initiate a direct Paystack mobile money charge asynchronously."""
        validated_email = validate_email_address(email)
        validated_currency = validate_currency(currency)
        minor_amount = _to_minor_units(amount, currency=validated_currency)
        if not isinstance(phone, str) or not phone.strip():
            raise ValueError("phone must be a non-empty string")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be a non-empty string")
        ref = _validate_paystack_reference(reference)
        response = await self._http.request(
            "POST",
            "/charge",
            headers=self._headers(),
            json={
                "email": validated_email,
                "amount": minor_amount,
                "currency": validated_currency,
                "reference": ref,
                "mobile_money": {
                    "phone": validate_header_value(phone.strip(), field_name="phone"),
                    "provider": validate_header_value(
                        provider.strip().lower(), field_name="provider"
                    ),
                },
            },
            idempotent=False,
            reference_id=ref,
        )
        return parse_json_dict(response, reference_id=ref)

    async def create_refund(
        self,
        transaction: str,
        *,
        amount: str | None = None,
        currency: str | None = None,
        customer_note: str | None = None,
        merchant_note: str | None = None,
    ) -> dict[str, Any]:
        """Create a Paystack refund asynchronously."""
        if not isinstance(transaction, str) or not transaction.strip():
            raise ValueError("transaction must be a non-empty string")
        tx_ref = validate_header_value(transaction.strip(), field_name="transaction")
        payload: dict[str, Any] = {"transaction": tx_ref}
        validated_currency = (
            validate_currency(currency) if currency is not None else None
        )
        if validated_currency is not None:
            payload["currency"] = validated_currency
        if amount is not None:
            payload["amount"] = _to_minor_units(amount, currency=validated_currency)
        if customer_note is not None:
            payload["customer_note"] = customer_note
        if merchant_note is not None:
            payload["merchant_note"] = merchant_note
        response = await self._http.request(
            "POST",
            "/refund",
            headers=self._headers(),
            json=payload,
            idempotent=False,
            reference_id=tx_ref,
        )
        return parse_json_dict(response, reference_id=tx_ref)

    async def verify_transfer(self, reference: str) -> dict[str, Any]:
        encoded = encode_path_segment(reference, field_name="reference")
        response = await self._http.request(
            "GET",
            f"/transfer/verify/{encoded}",
            headers=self._headers(),
            reference_id=reference,
        )
        return parse_json_dict(response, reference_id=reference)

    async def get_balance(self) -> dict[str, Any]:
        response = await self._http.request("GET", "/balance", headers=self._headers())
        return parse_json_dict(response)

    def verify_webhook(self, payload: bytes, signature: str) -> None:
        """Verify ``x-paystack-signature`` HMAC-SHA512 header against raw bytes."""
        WebhookHandler.verify_hmac_signature(
            payload, signature, self._config.secret_key, algorithm="sha512"
        )

    async def close(self) -> None:
        await self._http.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


def _resolve_paystack_recipient(request: DisbursementRequest) -> str:
    candidate = (request.payee_bank_code or request.payee_msisdn).strip()
    if not candidate.startswith("RCP_"):
        raise ValueError(
            "Paystack disbursements require a Paystack recipient code starting with 'RCP_'"
        )
    return candidate


def _resolve_paystack_ref(data: dict[str, Any], fallback: str) -> str:
    raw = data.get("reference")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return fallback


class PaystackProvider:
    """Synchronous unified provider adapter for Paystack."""

    def __init__(self, client: PaystackClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "paystack"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _PAYSTACK_CAPABILITIES

    def collect(self, request: PaymentRequest) -> PaymentResult:
        email = request.payer_email or self._client.default_customer_email
        if not email:
            raise ValueError(
                "payer_email or PaystackConfig.default_customer_email is required for Paystack collections"
            )
        ref = _validate_paystack_reference(request.reference_id)
        res = self._client.initialize_transaction(
            email=email,
            amount=request.amount,
            currency=request.currency,
            reference=ref,
            callback_url=request.callback_url,
        )
        data = _unwrap_paystack_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=_resolve_paystack_ref(data, ref),
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or None,
            checkout_url=data.get("authorization_url"),
            raw=res,
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        recipient = _resolve_paystack_recipient(request)
        ref = _validate_paystack_transfer_reference(request.reference_id)
        res = self._client.initiate_transfer(
            amount=request.amount,
            currency=request.currency,
            recipient=recipient,
            reference=ref,
            reason=request.payer_message or "Payout",
        )
        data = _unwrap_paystack_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=_resolve_paystack_ref(data, ref),
            status=_map_paystack_status(str(data.get("status", "pending"))),
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or None,
            raw=res,
        )

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        res = (
            self._client.verify_transfer(reference_id)
            if kind == "disbursement"
            else self._client.verify_transaction(reference_id)
        )
        return _map_paystack_status_response(self.name, reference_id, res)

    def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        validate_operation_kind(kind)
        res = self._client.get_balance()
        available, resolved_currency = _unwrap_paystack_balance(
            res, currency=currency or self._client.default_currency
        )
        return BalanceResult(
            provider=self.name,
            available_balance=available,
            currency=resolved_currency,
            raw=res,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncPaystackProvider:
    """Asynchronous unified provider adapter for Paystack."""

    def __init__(self, client: AsyncPaystackClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "paystack"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _PAYSTACK_CAPABILITIES

    async def collect(self, request: PaymentRequest) -> PaymentResult:
        email = request.payer_email or self._client.default_customer_email
        if not email:
            raise ValueError(
                "payer_email or PaystackConfig.default_customer_email is required for Paystack collections"
            )
        ref = _validate_paystack_reference(request.reference_id)
        res = await self._client.initialize_transaction(
            email=email,
            amount=request.amount,
            currency=request.currency,
            reference=ref,
            callback_url=request.callback_url,
        )
        data = _unwrap_paystack_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=_resolve_paystack_ref(data, ref),
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or None,
            checkout_url=data.get("authorization_url"),
            raw=res,
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        recipient = _resolve_paystack_recipient(request)
        ref = _validate_paystack_transfer_reference(request.reference_id)
        res = await self._client.initiate_transfer(
            amount=request.amount,
            currency=request.currency,
            recipient=recipient,
            reference=ref,
            reason=request.payer_message or "Payout",
        )
        data = _unwrap_paystack_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=_resolve_paystack_ref(data, ref),
            status=_map_paystack_status(str(data.get("status", "pending"))),
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or None,
            raw=res,
        )

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        res = (
            await self._client.verify_transfer(reference_id)
            if kind == "disbursement"
            else await self._client.verify_transaction(reference_id)
        )
        return _map_paystack_status_response(self.name, reference_id, res)

    async def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        validate_operation_kind(kind)
        res = await self._client.get_balance()
        available, resolved_currency = _unwrap_paystack_balance(
            res, currency=currency or self._client.default_currency
        )
        return BalanceResult(
            provider=self.name,
            available_balance=available,
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
