from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import httpx

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.exceptions import PyMomoSDKError
from py_momo_sdk.http import HttpClient, parse_json_dict
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
from py_momo_sdk.utils import (
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

_PAYSTACK_CAPABILITIES = ProviderCapabilities(
    provider_id="paystack",
    supports_collection=True,
    supports_disbursement=True,
    supports_balance=True,
    supports_webhook_hmac=True,
    currencies=("NGN", "GHS", "KES", "ZAR", "XOF", "USD"),
)


@dataclass
class PaystackConfig:
    """Credentials and settings for Paystack API."""

    secret_key: str
    callback_url: str | None = None
    default_customer_email: str | None = None
    base_url: str = PAYSTACK_BASE_URL
    timeout: float = 30.0
    max_retries: int = 0
    retry_backoff: float = 0.5

    def __post_init__(self) -> None:
        if not isinstance(self.secret_key, str) or not self.secret_key.strip():
            raise ValueError("secret_key must be a non-empty string")
        validate_header_value(self.secret_key, field_name="secret_key")
        if self.callback_url is not None:
            validate_callback_url(self.callback_url)
        if self.default_customer_email is not None:
            self.default_customer_email = validate_email_address(
                self.default_customer_email
            )
        validate_base_url(self.base_url)
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


def _to_minor_units(amount: str) -> int:
    validated = validate_amount(amount)
    scaled = Decimal(validated) * Decimal(100)
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


def _unwrap_paystack_balance(res: dict[str, Any]) -> tuple[str, str]:
    if res.get("status") is False:
        msg = res.get("message")
        raise PyMomoSDKError(
            str(msg) if isinstance(msg, str) and msg else "Paystack request failed"
        )
    items = res.get("data")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise PyMomoSDKError("Malformed Paystack balance response")
    first = items[0]
    if (
        "balance" not in first
        or not isinstance(first.get("currency"), str)
        or not first["currency"]
    ):
        raise PyMomoSDKError("Malformed Paystack balance response")
    return _from_minor_units(first["balance"]), first["currency"]


def _map_paystack_status(raw_status: str) -> NormalizedStatus:
    norm = raw_status.strip().lower()
    if norm in ("success", "succeeded"):
        return NormalizedStatus.SUCCEEDED
    if norm in ("failed", "abandoned"):
        return NormalizedStatus.FAILED
    if norm in ("reversed",):
        return NormalizedStatus.REVERSED
    return NormalizedStatus.PENDING


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
        self, config: PaystackConfig, *, client: httpx.Client | None = None
    ) -> None:
        self._config = config
        self._http = HttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            client=client,
        )

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
    ) -> dict[str, Any]:
        """Initialize a Paystack transaction (amounts converted to minor units)."""
        validated_email = validate_email_address(email)
        minor_amount = _to_minor_units(amount)
        validated_currency = validate_currency(currency)
        if callback_url is not None:
            validate_callback_url(callback_url)
        resolved_cb = callback_url or self._config.callback_url
        ref = reference or generate_reference_id()
        payload: dict[str, Any] = {
            "email": validated_email,
            "amount": minor_amount,
            "currency": validated_currency,
            "reference": ref,
        }
        if resolved_cb is not None:
            payload["callback_url"] = resolved_cb
        response = self._http.request(
            "POST",
            "/transaction/initialize",
            headers=self._headers(),
            json=payload,
        )
        return parse_json_dict(response)

    def verify_transaction(self, reference: str) -> dict[str, Any]:
        """Verify a Paystack transaction by reference."""
        encoded = encode_path_segment(reference, field_name="reference")
        response = self._http.request(
            "GET", f"/transaction/verify/{encoded}", headers=self._headers()
        )
        return parse_json_dict(response)

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
        minor_amount = _to_minor_units(amount)
        validated_currency = validate_currency(currency)
        if not isinstance(recipient, str) or not recipient.strip():
            raise ValueError("recipient must be a non-empty recipient code")
        validate_header_value(recipient.strip(), field_name="recipient")
        ref = reference or generate_reference_id()
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
        )
        return parse_json_dict(response)

    def verify_transfer(self, reference: str) -> dict[str, Any]:
        """Verify a Paystack transfer by reference."""
        encoded = encode_path_segment(reference, field_name="reference")
        response = self._http.request(
            "GET", f"/transfer/verify/{encoded}", headers=self._headers()
        )
        return parse_json_dict(response)

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
        self, config: PaystackConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._config = config
        self._http = AsyncHttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            client=client,
        )

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
    ) -> dict[str, Any]:
        validated_email = validate_email_address(email)
        minor_amount = _to_minor_units(amount)
        validated_currency = validate_currency(currency)
        if callback_url is not None:
            validate_callback_url(callback_url)
        resolved_cb = callback_url or self._config.callback_url
        ref = reference or generate_reference_id()
        payload: dict[str, Any] = {
            "email": validated_email,
            "amount": minor_amount,
            "currency": validated_currency,
            "reference": ref,
        }
        if resolved_cb is not None:
            payload["callback_url"] = resolved_cb
        response = await self._http.request(
            "POST",
            "/transaction/initialize",
            headers=self._headers(),
            json=payload,
        )
        return parse_json_dict(response)

    async def verify_transaction(self, reference: str) -> dict[str, Any]:
        encoded = encode_path_segment(reference, field_name="reference")
        response = await self._http.request(
            "GET", f"/transaction/verify/{encoded}", headers=self._headers()
        )
        return parse_json_dict(response)

    async def initiate_transfer(
        self,
        amount: str,
        currency: str,
        recipient: str,
        *,
        reference: str | None = None,
        reason: str = "Payout",
    ) -> dict[str, Any]:
        minor_amount = _to_minor_units(amount)
        validated_currency = validate_currency(currency)
        if not isinstance(recipient, str) or not recipient.strip():
            raise ValueError("recipient must be a non-empty recipient code")
        validate_header_value(recipient.strip(), field_name="recipient")
        ref = reference or generate_reference_id()
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
        )
        return parse_json_dict(response)

    async def verify_transfer(self, reference: str) -> dict[str, Any]:
        encoded = encode_path_segment(reference, field_name="reference")
        response = await self._http.request(
            "GET", f"/transfer/verify/{encoded}", headers=self._headers()
        )
        return parse_json_dict(response)

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
        email = request.payer_email or self._client._config.default_customer_email
        if not email:
            raise ValueError(
                "payer_email or PaystackConfig.default_customer_email is required for Paystack collections"
            )
        res = self._client.initialize_transaction(
            email=email,
            amount=request.amount,
            currency=request.currency,
            reference=request.reference_id,
            callback_url=request.callback_url,
        )
        data = _unwrap_paystack_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("reference", request.reference_id or "")),
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or None,
            checkout_url=data.get("authorization_url"),
            raw=res,
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        recipient = _resolve_paystack_recipient(request)
        res = self._client.initiate_transfer(
            amount=request.amount,
            currency=request.currency,
            recipient=recipient,
            reference=request.reference_id,
            reason=request.payer_message or "Payout",
        )
        data = _unwrap_paystack_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("reference", request.reference_id or "")),
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

    def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        validate_operation_kind(kind)
        res = self._client.get_balance()
        available, currency = _unwrap_paystack_balance(res)
        return BalanceResult(
            provider=self.name,
            available_balance=available,
            currency=currency,
            raw=res,
        )


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
        email = request.payer_email or self._client._config.default_customer_email
        if not email:
            raise ValueError(
                "payer_email or PaystackConfig.default_customer_email is required for Paystack collections"
            )
        res = await self._client.initialize_transaction(
            email=email,
            amount=request.amount,
            currency=request.currency,
            reference=request.reference_id,
            callback_url=request.callback_url,
        )
        data = _unwrap_paystack_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("reference", request.reference_id or "")),
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or None,
            checkout_url=data.get("authorization_url"),
            raw=res,
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        recipient = _resolve_paystack_recipient(request)
        res = await self._client.initiate_transfer(
            amount=request.amount,
            currency=request.currency,
            recipient=recipient,
            reference=request.reference_id,
            reason=request.payer_message or "Payout",
        )
        data = _unwrap_paystack_data(res)
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("reference", request.reference_id or "")),
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

    async def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        validate_operation_kind(kind)
        res = await self._client.get_balance()
        available, currency = _unwrap_paystack_balance(res)
        return BalanceResult(
            provider=self.name,
            available_balance=available,
            currency=currency,
            raw=res,
        )
