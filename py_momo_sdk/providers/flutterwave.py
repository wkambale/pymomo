from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.exceptions import PyMomoSDKError
from py_momo_sdk.frameworks import verify_constant_time_token
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
    base_url: str = FLUTTERWAVE_BASE_URL
    timeout: float = 30.0
    max_retries: int = 0
    retry_backoff: float = 0.5

    def __post_init__(self) -> None:
        if not isinstance(self.secret_key, str) or not self.secret_key.strip():
            raise ValueError("secret_key must be a non-empty string")
        validate_header_value(self.secret_key, field_name="secret_key")
        if self.webhook_hash is not None:
            validate_header_value(self.webhook_hash, field_name="webhook_hash")
        if self.redirect_url is not None:
            validate_callback_url(self.redirect_url)
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
        validate_base_url(self.base_url)
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
    if norm in ("failed", "cancelled", "canceled"):
        return NormalizedStatus.FAILED
    return NormalizedStatus.PENDING


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
        self, config: FlutterwaveConfig, *, client: httpx.Client | None = None
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
        validated_amount = validate_amount(amount)
        validated_currency = validate_currency(currency)
        resolved_email = email or self._config.default_customer_email
        if not resolved_email:
            raise ValueError(
                "email or FlutterwaveConfig.default_customer_email is required for Flutterwave payments"
            )
        validated_email = validate_email_address(resolved_email)
        if redirect_url is not None:
            validate_callback_url(redirect_url)
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
        account_bank: str | None = None,
        reference: str | None = None,
        narration: str = "Payout",
    ) -> dict[str, Any]:
        """Initiate a Flutterwave transfer."""
        validated_amount = validate_amount(amount)
        validated_currency = validate_currency(currency)
        resolved_bank = account_bank or self._config.default_account_bank
        if not resolved_bank or not resolved_bank.strip():
            raise ValueError(
                "account_bank or FlutterwaveConfig.default_account_bank is required for Flutterwave transfers"
            )
        validated_bank = validate_header_value(
            resolved_bank.strip(), field_name="account_bank"
        )
        ref = reference or generate_reference_id()
        response = self._http.request(
            "POST",
            "/v3/transfers",
            headers=self._headers(),
            json={
                "account_bank": validated_bank,
                "account_number": normalise_msisdn(account_number),
                "amount": validated_amount,
                "currency": validated_currency,
                "narration": narration,
                "reference": ref,
            },
        )
        return parse_json_dict(response)

    def get_transfer(self, transfer_id: str) -> dict[str, Any]:
        """Retrieve a Flutterwave transfer by ID."""
        encoded = encode_path_segment(transfer_id, field_name="transfer_id")
        response = self._http.request(
            "GET",
            f"/v3/transfers/{encoded}",
            headers=self._headers(),
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
            retry_backoff=config.retry_backoff,
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
        email: str | None = None,
        tx_ref: str | None = None,
        redirect_url: str | None = None,
    ) -> dict[str, Any]:
        validated_amount = validate_amount(amount)
        validated_currency = validate_currency(currency)
        resolved_email = email or self._config.default_customer_email
        if not resolved_email:
            raise ValueError(
                "email or FlutterwaveConfig.default_customer_email is required for Flutterwave payments"
            )
        validated_email = validate_email_address(resolved_email)
        if redirect_url is not None:
            validate_callback_url(redirect_url)
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
        account_bank: str | None = None,
        reference: str | None = None,
        narration: str = "Payout",
    ) -> dict[str, Any]:
        validated_amount = validate_amount(amount)
        validated_currency = validate_currency(currency)
        resolved_bank = account_bank or self._config.default_account_bank
        if not resolved_bank or not resolved_bank.strip():
            raise ValueError(
                "account_bank or FlutterwaveConfig.default_account_bank is required for Flutterwave transfers"
            )
        validated_bank = validate_header_value(
            resolved_bank.strip(), field_name="account_bank"
        )
        ref = reference or generate_reference_id()
        response = await self._http.request(
            "POST",
            "/v3/transfers",
            headers=self._headers(),
            json={
                "account_bank": validated_bank,
                "account_number": normalise_msisdn(account_number),
                "amount": validated_amount,
                "currency": validated_currency,
                "narration": narration,
                "reference": ref,
            },
        )
        return parse_json_dict(response)

    async def get_transfer(self, transfer_id: str) -> dict[str, Any]:
        encoded = encode_path_segment(transfer_id, field_name="transfer_id")
        response = await self._http.request(
            "GET",
            f"/v3/transfers/{encoded}",
            headers=self._headers(),
        )
        return parse_json_dict(response)

    async def get_balance(self, currency: str = "NGN") -> dict[str, Any]:
        iso = validate_currency(currency)
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

    def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        validate_operation_kind(kind)
        res = self._client.get_balance()
        avail, currency = _unwrap_flw_balance(res)
        return BalanceResult(
            provider=self.name,
            available_balance=avail,
            currency=currency,
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

    async def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        validate_operation_kind(kind)
        res = await self._client.get_balance()
        avail, currency = _unwrap_flw_balance(res)
        return BalanceResult(
            provider=self.name,
            available_balance=avail,
            currency=currency,
            raw=res,
        )
