from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.frameworks import verify_constant_time_token
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
    normalise_msisdn,
    validate_callback_url,
    validate_currency,
    validate_header_value,
    validate_timeout,
)

if TYPE_CHECKING:
    from typing_extensions import Self

FLUTTERWAVE_BASE_URL = "https://api.flutterwave.com"

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
    redirect_url: str = "https://example.com/flutterwave/callback"
    base_url: str = FLUTTERWAVE_BASE_URL
    timeout: float = 30.0
    max_retries: int = 0

    def __post_init__(self) -> None:
        validate_header_value(self.secret_key, field_name="secret_key")
        if self.webhook_hash is not None:
            validate_header_value(self.webhook_hash, field_name="webhook_hash")
        validate_callback_url(self.redirect_url)
        self.timeout = validate_timeout(self.timeout)

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
    if norm in ("failed", "cancelled", "canceled"):
        return NormalizedStatus.FAILED
    return NormalizedStatus.PENDING


class FlutterwaveClient:
    """Synchronous Flutterwave v3 API client."""

    def __init__(
        self, config: FlutterwaveConfig, *, client: httpx.Client | None = None
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

    def create_payment(
        self,
        amount: str,
        currency: str,
        phone_number: str,
        *,
        tx_ref: str | None = None,
        redirect_url: str | None = None,
    ) -> dict[str, Any]:
        """Create a Flutterwave standard payment link."""
        ref = tx_ref or generate_reference_id()
        response = self._http.request(
            "POST",
            "/v3/payments",
            headers=self._headers(),
            json={
                "tx_ref": ref,
                "amount": amount,
                "currency": currency,
                "redirect_url": redirect_url or self._config.redirect_url,
                "customer": {
                    "email": f"{normalise_msisdn(phone_number)}@mobilemoney.example.com",
                    "phonenumber": normalise_msisdn(phone_number),
                },
            },
        )
        return parse_json_dict(response)

    def verify_by_reference(self, tx_ref: str) -> dict[str, Any]:
        """Verify a Flutterwave transaction by ``tx_ref``."""
        encoded = encode_path_segment(tx_ref, field_name="tx_ref")
        response = self._http.request(
            "GET",
            f"/v3/transactions/verify_by_reference?tx_ref={encoded}",
            headers=self._headers(),
        )
        return parse_json_dict(response)

    def create_transfer(
        self,
        amount: str,
        currency: str,
        account_number: str,
        *,
        reference: str | None = None,
        narration: str = "Payout",
    ) -> dict[str, Any]:
        """Initiate a Flutterwave transfer."""
        ref = reference or generate_reference_id()
        response = self._http.request(
            "POST",
            "/v3/transfers",
            headers=self._headers(),
            json={
                "account_bank": "MPS",
                "account_number": normalise_msisdn(account_number),
                "amount": amount,
                "currency": currency,
                "narration": narration,
                "reference": ref,
            },
        )
        return parse_json_dict(response)

    def get_balance(self, currency: str = "NGN") -> dict[str, Any]:
        """Retrieve Flutterwave wallet balance for a currency."""
        iso = validate_currency(currency)
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
        self, config: FlutterwaveConfig, *, client: httpx.AsyncClient | None = None
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

    async def create_payment(
        self,
        amount: str,
        currency: str,
        phone_number: str,
        *,
        tx_ref: str | None = None,
        redirect_url: str | None = None,
    ) -> dict[str, Any]:
        ref = tx_ref or generate_reference_id()
        response = await self._http.request(
            "POST",
            "/v3/payments",
            headers=self._headers(),
            json={
                "tx_ref": ref,
                "amount": amount,
                "currency": currency,
                "redirect_url": redirect_url or self._config.redirect_url,
                "customer": {
                    "email": f"{normalise_msisdn(phone_number)}@mobilemoney.example.com",
                    "phonenumber": normalise_msisdn(phone_number),
                },
            },
        )
        return parse_json_dict(response)

    async def verify_by_reference(self, tx_ref: str) -> dict[str, Any]:
        encoded = encode_path_segment(tx_ref, field_name="tx_ref")
        response = await self._http.request(
            "GET",
            f"/v3/transactions/verify_by_reference?tx_ref={encoded}",
            headers=self._headers(),
        )
        return parse_json_dict(response)

    async def create_transfer(
        self,
        amount: str,
        currency: str,
        account_number: str,
        *,
        reference: str | None = None,
        narration: str = "Payout",
    ) -> dict[str, Any]:
        ref = reference or generate_reference_id()
        response = await self._http.request(
            "POST",
            "/v3/transfers",
            headers=self._headers(),
            json={
                "account_bank": "MPS",
                "account_number": normalise_msisdn(account_number),
                "amount": amount,
                "currency": currency,
                "narration": narration,
                "reference": ref,
            },
        )
        return parse_json_dict(response)

    async def get_balance(self, currency: str = "NGN") -> dict[str, Any]:
        iso = validate_currency(currency)
        response = await self._http.request(
            "GET", f"/v3/balances/{iso}", headers=self._headers()
        )
        return parse_json_dict(response)

    async def close(self) -> None:
        await self._http.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


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
            tx_ref=ref,
            redirect_url=request.callback_url,
        )
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            checkout_url=data.get("link"),
            raw=res,
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        ref = request.reference_id or generate_reference_id()
        res = self._client.create_transfer(
            amount=request.amount,
            currency=request.currency,
            account_number=request.payee_msisdn,
            reference=ref,
            narration=request.payer_message or "Payout",
        )
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("reference", ref)),
            status=_map_flw_status(str(data.get("status", "pending"))),
            amount=request.amount,
            currency=request.currency,
            raw=res,
        )

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        del kind
        res = self._client.verify_by_reference(reference_id)
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=reference_id,
            status=_map_flw_status(str(data.get("status", "pending"))),
            currency=data.get("currency"),
            raw=res,
        )

    def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        del kind
        res = self._client.get_balance()
        data = res.get("data", {})
        return BalanceResult(
            provider=self.name,
            available_balance=str(data.get("available_balance", "0.00")),
            currency=str(data.get("currency", "NGN")),
            raw=res,
        )


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
            tx_ref=ref,
            redirect_url=request.callback_url,
        )
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            checkout_url=data.get("link"),
            raw=res,
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        ref = request.reference_id or generate_reference_id()
        res = await self._client.create_transfer(
            amount=request.amount,
            currency=request.currency,
            account_number=request.payee_msisdn,
            reference=ref,
            narration=request.payer_message or "Payout",
        )
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=str(data.get("reference", ref)),
            status=_map_flw_status(str(data.get("status", "pending"))),
            amount=request.amount,
            currency=request.currency,
            raw=res,
        )

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        del kind
        res = await self._client.verify_by_reference(reference_id)
        data = res.get("data", {})
        return PaymentResult(
            provider=self.name,
            reference_id=reference_id,
            status=_map_flw_status(str(data.get("status", "pending"))),
            currency=data.get("currency"),
            raw=res,
        )

    async def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        del kind
        res = await self._client.get_balance()
        data = res.get("data", {})
        return BalanceResult(
            provider=self.name,
            available_balance=str(data.get("available_balance", "0.00")),
            currency=str(data.get("currency", "NGN")),
            raw=res,
        )
