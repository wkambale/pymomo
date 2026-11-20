from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, ConfigDict

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.http import HttpClient, parse_json_dict
from py_momo_sdk.providers.models import (
    BalanceResult,
    DisbursementRequest,
    NormalizedStatus,
    PaymentRequest,
    PaymentResult,
    ProviderCapabilities,
)
from py_momo_sdk.utils import (
    encode_path_segment,
    generate_reference_id,
    validate_callback_url,
    validate_header_value,
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
    callback_url: str = "https://example.com/paystack/callback"
    base_url: str = PAYSTACK_BASE_URL
    timeout: float = 30.0
    max_retries: int = 0

    def __post_init__(self) -> None:
        validate_header_value(self.secret_key, field_name="secret_key")
        validate_callback_url(self.callback_url)
        self.timeout = validate_timeout(self.timeout)

    def __repr__(self) -> str:
        return (
            f"PaystackConfig(secret_key=<redacted>, "
            f"base_url={self.base_url!r}, timeout={self.timeout!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class PaystackEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: bool
    message: str = ""
    data: Any = None


def _to_minor_units(amount: str) -> int:
    return int(Decimal(amount) * 100)


def _map_paystack_status(raw_status: str) -> NormalizedStatus:
    norm = raw_status.strip().lower()
    if norm in ("success", "succeeded"):
        return NormalizedStatus.SUCCEEDED
    if norm in ("failed", "abandoned"):
        return NormalizedStatus.FAILED
    if norm in ("reversed",):
        return NormalizedStatus.REVERSED
    return NormalizedStatus.PENDING


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
        ref = reference or generate_reference_id()
        response = self._http.request(
            "POST",
            "/transaction/initialize",
            headers=self._headers(),
            json={
                "email": email,
                "amount": _to_minor_units(amount),
                "currency": currency,
                "reference": ref,
                "callback_url": callback_url or self._config.callback_url,
            },
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
        ref = reference or generate_reference_id()
        response = self._http.request(
            "POST",
            "/transfer",
            headers=self._headers(),
            json={
                "source": "balance",
                "amount": _to_minor_units(amount),
                "currency": currency,
                "recipient": recipient,
                "reference": ref,
                "reason": reason,
            },
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
        ref = reference or generate_reference_id()
        response = await self._http.request(
            "POST",
            "/transaction/initialize",
            headers=self._headers(),
            json={
                "email": email,
                "amount": _to_minor_units(amount),
                "currency": currency,
                "reference": ref,
                "callback_url": callback_url or self._config.callback_url,
            },
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
        ref = reference or generate_reference_id()
        response = await self._http.request(
            "POST",
            "/transfer",
            headers=self._headers(),
            json={
                "source": "balance",
                "amount": _to_minor_units(amount),
                "currency": currency,
                "recipient": recipient,
                "reference": ref,
                "reason": reason,
            },
        )
        return parse_json_dict(response)

    async def get_balance(self) -> dict[str, Any]:
        response = await self._http.request("GET", "/balance", headers=self._headers())
        return parse_json_dict(response)

    async def close(self) -> None:
        await self._http.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


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
        email = f"{request.payer_msisdn}@mobilemoney.example.com"
        res = self._client.initialize_transaction(
            email=email,
            amount=request.amount,
            currency=request.currency,
            reference=request.reference_id,
            callback_url=request.callback_url,
        )
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("reference", request.reference_id or "")),
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            checkout_url=data.get("authorization_url"),
            raw=res,
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        res = self._client.initiate_transfer(
            amount=request.amount,
            currency=request.currency,
            recipient=request.payee_msisdn,
            reference=request.reference_id,
            reason=request.payer_message or "Payout",
        )
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("reference", request.reference_id or "")),
            status=_map_paystack_status(str(data.get("status", "pending"))),
            amount=request.amount,
            currency=request.currency,
            raw=res,
        )

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        del kind
        res = self._client.verify_transaction(reference_id)
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=reference_id,
            status=_map_paystack_status(str(data.get("status", "pending"))),
            currency=data.get("currency"),
            raw=res,
        )

    def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        del kind
        res = self._client.get_balance()
        items = res.get("data", [])
        first = items[0] if isinstance(items, list) and items else {}
        minor = int(first.get("balance", 0))
        return BalanceResult(
            provider=self.name,
            available_balance=f"{minor / 100:.2f}",
            currency=str(first.get("currency", "NGN")),
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
        email = f"{request.payer_msisdn}@mobilemoney.example.com"
        res = await self._client.initialize_transaction(
            email=email,
            amount=request.amount,
            currency=request.currency,
            reference=request.reference_id,
            callback_url=request.callback_url,
        )
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("reference", request.reference_id or "")),
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            checkout_url=data.get("authorization_url"),
            raw=res,
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        res = await self._client.initiate_transfer(
            amount=request.amount,
            currency=request.currency,
            recipient=request.payee_msisdn,
            reference=request.reference_id,
            reason=request.payer_message or "Payout",
        )
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("reference", request.reference_id or "")),
            status=_map_paystack_status(str(data.get("status", "pending"))),
            amount=request.amount,
            currency=request.currency,
            raw=res,
        )

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        del kind
        res = await self._client.verify_transaction(reference_id)
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=reference_id,
            status=_map_paystack_status(str(data.get("status", "pending"))),
            currency=data.get("currency"),
            raw=res,
        )

    async def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        del kind
        res = await self._client.get_balance()
        items = res.get("data", [])
        first = items[0] if isinstance(items, list) and items else {}
        minor = int(first.get("balance", 0))
        return BalanceResult(
            provider=self.name,
            available_balance=f"{minor / 100:.2f}",
            currency=str(first.get("currency", "NGN")),
            raw=res,
        )
