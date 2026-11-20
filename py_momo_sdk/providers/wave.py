from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, ConfigDict

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.http import HttpClient, parse_model
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
    normalise_msisdn,
    validate_callback_url,
    validate_header_value,
    validate_timeout,
)
from py_momo_sdk.webhooks import WebhookHandler

if TYPE_CHECKING:
    from typing_extensions import Self

WAVE_BASE_URL = "https://api.wave.com"

_WAVE_CAPABILITIES = ProviderCapabilities(
    provider_id="wave",
    supports_collection=True,
    supports_disbursement=True,
    supports_balance=True,
    supports_webhook_hmac=True,
    currencies=("XOF", "UGX"),
)


@dataclass
class WaveConfig:
    """Credentials and settings for Wave Mobile Money API."""

    api_key: str
    webhook_secret: str | None = None
    success_url: str = "https://example.com/success"
    error_url: str = "https://example.com/error"
    base_url: str = WAVE_BASE_URL
    timeout: float = 30.0
    max_retries: int = 0

    def __post_init__(self) -> None:
        validate_header_value(self.api_key, field_name="api_key")
        if self.webhook_secret is not None:
            validate_header_value(self.webhook_secret, field_name="webhook_secret")
        validate_callback_url(self.success_url)
        validate_callback_url(self.error_url)
        self.timeout = validate_timeout(self.timeout)
        if isinstance(self.max_retries, bool) or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")

    def __repr__(self) -> str:
        return (
            f"WaveConfig(api_key=<redacted>, webhook_secret=<redacted>, "
            f"base_url={self.base_url!r}, timeout={self.timeout!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class WaveCheckoutSession(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    amount: str
    currency: str
    checkout_status: str = "open"
    payment_status: str = "processing"
    wave_launch_url: str | None = None
    client_reference: str | None = None


class WavePayoutResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    amount: str
    currency: str
    status: str = "processing"
    client_reference: str | None = None


class WaveBalanceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    amount: str
    currency: str


def _map_wave_status(raw_status: str) -> NormalizedStatus:
    normalized = raw_status.strip().lower()
    if normalized in ("succeeded", "complete", "completed"):
        return NormalizedStatus.SUCCEEDED
    if normalized in ("expired",):
        return NormalizedStatus.EXPIRED
    if normalized in ("cancelled", "canceled", "failed", "reversed"):
        return NormalizedStatus.FAILED
    return NormalizedStatus.PENDING


class WaveClient:
    """Synchronous Wave Mobile Money client."""

    def __init__(
        self, config: WaveConfig, *, client: httpx.Client | None = None
    ) -> None:
        self._config = config
        self._http = HttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            client=client,
        )

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
            headers["X-Reference-Id"] = idempotency_key
        return headers

    def create_checkout_session(
        self,
        amount: str,
        currency: str,
        *,
        client_reference: str | None = None,
        success_url: str | None = None,
        error_url: str | None = None,
    ) -> WaveCheckoutSession:
        """Create a Wave checkout session."""
        ref = client_reference or generate_reference_id()
        payload: dict[str, Any] = {
            "amount": amount,
            "currency": currency,
            "success_url": success_url or self._config.success_url,
            "error_url": error_url or self._config.error_url,
            "client_reference": ref,
        }
        response = self._http.request(
            "POST",
            "/v1/checkout/sessions",
            headers=self._headers(idempotency_key=ref),
            json=payload,
        )
        return parse_model(response, WaveCheckoutSession)

    def get_checkout_session(self, session_id: str) -> WaveCheckoutSession:
        """Retrieve a Wave checkout session by ID."""
        encoded = encode_path_segment(session_id, field_name="session_id")
        response = self._http.request(
            "GET",
            f"/v1/checkout/sessions/{encoded}",
            headers=self._headers(),
        )
        return parse_model(response, WaveCheckoutSession)

    def create_payout(
        self,
        amount: str,
        currency: str,
        mobile: str,
        *,
        client_reference: str | None = None,
    ) -> WavePayoutResponse:
        """Send a Wave payout to a subscriber mobile number."""
        ref = client_reference or generate_reference_id()
        response = self._http.request(
            "POST",
            "/v1/payout",
            headers=self._headers(idempotency_key=ref),
            json={
                "amount": amount,
                "currency": currency,
                "mobile": f"+{normalise_msisdn(mobile)}",
                "client_reference": ref,
            },
        )
        return parse_model(response, WavePayoutResponse)

    def get_payout(self, payout_id: str) -> WavePayoutResponse:
        """Retrieve a Wave payout status by ID."""
        encoded = encode_path_segment(payout_id, field_name="payout_id")
        response = self._http.request(
            "GET",
            f"/v1/payout/{encoded}",
            headers=self._headers(),
        )
        return parse_model(response, WavePayoutResponse)

    def get_balance(self) -> WaveBalanceResponse:
        """Retrieve the Wave merchant balance."""
        response = self._http.request(
            "GET",
            "/v1/balance",
            headers=self._headers(),
        )
        return parse_model(response, WaveBalanceResponse)

    def verify_webhook(
        self, payload: bytes, signature_header: str, *, tolerance_seconds: int = 300
    ) -> None:
        """Verify a ``Wave-Signature`` header against raw request body bytes."""
        WebhookHandler.verify_timestamped_hmac_signature(
            payload,
            signature_header,
            self._config.webhook_secret or "",
            tolerance_seconds=tolerance_seconds,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncWaveClient:
    """Asynchronous Wave Mobile Money client."""

    def __init__(
        self, config: WaveConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._config = config
        self._http = AsyncHttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            client=client,
        )

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
            headers["X-Reference-Id"] = idempotency_key
        return headers

    async def create_checkout_session(
        self,
        amount: str,
        currency: str,
        *,
        client_reference: str | None = None,
        success_url: str | None = None,
        error_url: str | None = None,
    ) -> WaveCheckoutSession:
        ref = client_reference or generate_reference_id()
        response = await self._http.request(
            "POST",
            "/v1/checkout/sessions",
            headers=self._headers(idempotency_key=ref),
            json={
                "amount": amount,
                "currency": currency,
                "success_url": success_url or self._config.success_url,
                "error_url": error_url or self._config.error_url,
                "client_reference": ref,
            },
        )
        return parse_model(response, WaveCheckoutSession)

    async def get_checkout_session(self, session_id: str) -> WaveCheckoutSession:
        encoded = encode_path_segment(session_id, field_name="session_id")
        response = await self._http.request(
            "GET",
            f"/v1/checkout/sessions/{encoded}",
            headers=self._headers(),
        )
        return parse_model(response, WaveCheckoutSession)

    async def create_payout(
        self,
        amount: str,
        currency: str,
        mobile: str,
        *,
        client_reference: str | None = None,
    ) -> WavePayoutResponse:
        ref = client_reference or generate_reference_id()
        response = await self._http.request(
            "POST",
            "/v1/payout",
            headers=self._headers(idempotency_key=ref),
            json={
                "amount": amount,
                "currency": currency,
                "mobile": f"+{normalise_msisdn(mobile)}",
                "client_reference": ref,
            },
        )
        return parse_model(response, WavePayoutResponse)

    async def get_payout(self, payout_id: str) -> WavePayoutResponse:
        encoded = encode_path_segment(payout_id, field_name="payout_id")
        response = await self._http.request(
            "GET",
            f"/v1/payout/{encoded}",
            headers=self._headers(),
        )
        return parse_model(response, WavePayoutResponse)

    async def get_balance(self) -> WaveBalanceResponse:
        response = await self._http.request(
            "GET",
            "/v1/balance",
            headers=self._headers(),
        )
        return parse_model(response, WaveBalanceResponse)

    async def close(self) -> None:
        await self._http.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


class WaveProvider:
    """Synchronous unified provider adapter for Wave."""

    def __init__(self, client: WaveClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "wave"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _WAVE_CAPABILITIES

    def collect(self, request: PaymentRequest) -> PaymentResult:
        session = self._client.create_checkout_session(
            amount=request.amount,
            currency=request.currency,
            client_reference=request.reference_id or request.external_id or None,
            success_url=request.callback_url,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=session.id,
            status=_map_wave_status(session.payment_status),
            amount=session.amount,
            currency=session.currency,
            external_id=session.client_reference,
            checkout_url=session.wave_launch_url,
            raw=session.model_dump(mode="json"),
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        payout = self._client.create_payout(
            amount=request.amount,
            currency=request.currency,
            mobile=request.payee_msisdn,
            client_reference=request.reference_id or request.external_id or None,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=payout.id,
            status=_map_wave_status(payout.status),
            amount=payout.amount,
            currency=payout.currency,
            external_id=payout.client_reference,
            raw=payout.model_dump(mode="json"),
        )

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        if kind == "disbursement":
            payout = self._client.get_payout(reference_id)
            return PaymentResult(
                provider=self.name,
                reference_id=payout.id,
                status=_map_wave_status(payout.status),
                amount=payout.amount,
                currency=payout.currency,
                external_id=payout.client_reference,
                raw=payout.model_dump(mode="json"),
            )
        session = self._client.get_checkout_session(reference_id)
        return PaymentResult(
            provider=self.name,
            reference_id=session.id,
            status=_map_wave_status(session.payment_status),
            amount=session.amount,
            currency=session.currency,
            external_id=session.client_reference,
            checkout_url=session.wave_launch_url,
            raw=session.model_dump(mode="json"),
        )

    def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        del kind
        balance = self._client.get_balance()
        return BalanceResult(
            provider=self.name,
            available_balance=balance.amount,
            currency=balance.currency,
            raw=balance.model_dump(mode="json"),
        )


class AsyncWaveProvider:
    """Asynchronous unified provider adapter for Wave."""

    def __init__(self, client: AsyncWaveClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "wave"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _WAVE_CAPABILITIES

    async def collect(self, request: PaymentRequest) -> PaymentResult:
        session = await self._client.create_checkout_session(
            amount=request.amount,
            currency=request.currency,
            client_reference=request.reference_id or request.external_id or None,
            success_url=request.callback_url,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=session.id,
            status=_map_wave_status(session.payment_status),
            amount=session.amount,
            currency=session.currency,
            external_id=session.client_reference,
            checkout_url=session.wave_launch_url,
            raw=session.model_dump(mode="json"),
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        payout = await self._client.create_payout(
            amount=request.amount,
            currency=request.currency,
            mobile=request.payee_msisdn,
            client_reference=request.reference_id or request.external_id or None,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=payout.id,
            status=_map_wave_status(payout.status),
            amount=payout.amount,
            currency=payout.currency,
            external_id=payout.client_reference,
            raw=payout.model_dump(mode="json"),
        )

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        if kind == "disbursement":
            payout = await self._client.get_payout(reference_id)
            return PaymentResult(
                provider=self.name,
                reference_id=payout.id,
                status=_map_wave_status(payout.status),
                amount=payout.amount,
                currency=payout.currency,
                external_id=payout.client_reference,
                raw=payout.model_dump(mode="json"),
            )
        session = await self._client.get_checkout_session(reference_id)
        return PaymentResult(
            provider=self.name,
            reference_id=session.id,
            status=_map_wave_status(session.payment_status),
            amount=session.amount,
            currency=session.currency,
            external_id=session.client_reference,
            checkout_url=session.wave_launch_url,
            raw=session.model_dump(mode="json"),
        )

    async def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        del kind
        balance = await self._client.get_balance()
        return BalanceResult(
            provider=self.name,
            available_balance=balance.amount,
            currency=balance.currency,
            raw=balance.model_dump(mode="json"),
        )
