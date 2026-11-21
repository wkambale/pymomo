from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.auth import TokenCache
from py_momo_sdk.http import HttpClient, parse_json_dict, parse_model
from py_momo_sdk.providers.models import (
    BalanceResult,
    DisbursementRequest,
    NormalizedStatus,
    PaymentRequest,
    PaymentResult,
    ProviderCapabilities,
)
from py_momo_sdk.utils import (
    build_basic_auth_header,
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

if TYPE_CHECKING:
    from typing_extensions import Self

ORANGE_BASE_URL = "https://api.orange.com"

_ORANGE_CAPABILITIES = ProviderCapabilities(
    provider_id="orange_money",
    supports_collection=True,
    supports_disbursement=False,
    supports_balance=False,
    supports_webhook_hmac=False,
    currencies=("XOF", "XAF", "OUV"),
)


@dataclass
class OrangeMoneyConfig:
    """Credentials and settings for Orange Money Web Payment API."""

    client_id: str
    client_secret: str
    merchant_key: str
    return_url: str | None = None
    cancel_url: str | None = None
    notif_url: str | None = None
    base_url: str = ORANGE_BASE_URL
    timeout: float = 30.0
    max_retries: int = 0
    retry_backoff: float = 0.5

    def __post_init__(self) -> None:
        for fname, fval in (
            ("client_id", self.client_id),
            ("client_secret", self.client_secret),
            ("merchant_key", self.merchant_key),
        ):
            if not isinstance(fval, str) or not fval.strip():
                raise ValueError(f"{fname} must be a non-empty string")
            validate_header_value(fval, field_name=fname)
        if self.return_url is not None:
            validate_callback_url(self.return_url)
        if self.cancel_url is not None:
            validate_callback_url(self.cancel_url)
        if self.notif_url is not None:
            validate_callback_url(self.notif_url)
        validate_base_url(self.base_url)
        self.timeout = validate_timeout(self.timeout)
        self.max_retries = validate_max_retries(self.max_retries)
        self.retry_backoff = validate_retry_backoff(self.retry_backoff)

    def __repr__(self) -> str:
        return (
            f"OrangeMoneyConfig(client_secret=<redacted>, "
            f"merchant_key=<redacted>, base_url={self.base_url!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class OrangeTokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str
    expires_in: int = Field(default=3600, gt=0)

    @field_validator("access_token")
    @classmethod
    def _check_access_token(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("access_token must not be empty")
        return validate_header_value(value, field_name="access_token")

    @field_validator("expires_in", mode="before")
    @classmethod
    def _check_expires_in(cls, value: object) -> object:
        if type(value) in (bool, float):
            raise ValueError("expires_in must be a positive integer")
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped.isascii() or not stripped.isdigit():
                raise ValueError("expires_in must be a positive integer")
        return value

    def __repr__(self) -> str:
        return f"OrangeTokenResponse(access_token=<redacted>, expires_in={self.expires_in!r})"

    def __str__(self) -> str:
        return self.__repr__()


def _map_orange_status(raw_status: str) -> NormalizedStatus:
    norm = raw_status.strip().upper()
    if norm in ("SUCCESS", "SUCCESSFUL"):
        return NormalizedStatus.SUCCEEDED
    if norm in ("FAILED", "EXPIRED"):
        return NormalizedStatus.FAILED
    return NormalizedStatus.PENDING


class OrangeMoneyClient:
    """Synchronous Orange Money Web Payment client."""

    def __init__(
        self, config: OrangeMoneyConfig, *, client: httpx.Client | None = None
    ) -> None:
        self._config = config
        self._cache = TokenCache()
        self._token_lock = threading.Lock()
        self._http = HttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            client=client,
        )

    def _get_token(self) -> str:
        cached = self._cache.get("orange_money")
        if cached:
            return cached
        with self._token_lock:
            cached = self._cache.get("orange_money")
            if cached:
                return cached
            response = self._http.request(
                "POST",
                "/oauth/v3/token",
                headers={
                    "Authorization": build_basic_auth_header(
                        self._config.client_id, self._config.client_secret
                    ),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
            )
            tok = parse_model(response, OrangeTokenResponse)
            self._cache.set("orange_money", tok.access_token, tok.expires_in)
            return tok.access_token

    def create_web_payment(
        self,
        amount: str,
        currency: str,
        *,
        order_id: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
        notif_url: str | None = None,
    ) -> dict[str, Any]:
        """Initialize an Orange Money web payment session."""
        validated_amount = validate_amount(amount)
        validated_currency = validate_currency(currency)
        for u in (return_url, cancel_url, notif_url):
            if u is not None:
                validate_callback_url(u)
        resolved_notif = notif_url or self._config.notif_url
        resolved_return = return_url or self._config.return_url or resolved_notif
        resolved_cancel = cancel_url or self._config.cancel_url or resolved_notif
        if not resolved_notif or not resolved_return or not resolved_cancel:
            raise ValueError(
                "return_url, cancel_url, and notif_url are required for Orange Money"
            )
        ref = order_id or generate_reference_id()
        response = self._http.request(
            "POST",
            "/orange-money-webpay/dev/v1/webpayment",
            headers={
                "Authorization": f"Bearer {self._get_token()}",
                "Content-Type": "application/json",
            },
            json={
                "merchant_key": self._config.merchant_key,
                "currency": validated_currency,
                "order_id": ref,
                "amount": validated_amount,
                "return_url": resolved_return,
                "cancel_url": resolved_cancel,
                "notif_url": resolved_notif,
                "lang": "en",
            },
            product_name="orange_money",
            token_cache=self._cache,
            token_refresher=self._get_token,
        )
        return parse_json_dict(response)

    def get_transaction_status(
        self, order_id: str, amount: str, pay_token: str
    ) -> dict[str, Any]:
        """Check Orange Money transaction status."""
        response = self._http.request(
            "POST",
            "/orange-money-webpay/dev/v1/transactionstatus",
            headers={
                "Authorization": f"Bearer {self._get_token()}",
                "Content-Type": "application/json",
            },
            json={
                "order_id": order_id,
                "amount": amount,
                "pay_token": pay_token,
            },
            product_name="orange_money",
            token_cache=self._cache,
            token_refresher=self._get_token,
        )
        return parse_json_dict(response)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncOrangeMoneyClient:
    """Asynchronous Orange Money Web Payment client."""

    def __init__(
        self, config: OrangeMoneyConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._config = config
        self._cache = TokenCache()
        self._token_lock = asyncio.Lock()
        self._http = AsyncHttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            client=client,
        )

    async def _get_token(self) -> str:
        cached = self._cache.get("orange_money")
        if cached:
            return cached
        async with self._token_lock:
            cached = self._cache.get("orange_money")
            if cached:
                return cached
            response = await self._http.request(
                "POST",
                "/oauth/v3/token",
                headers={
                    "Authorization": build_basic_auth_header(
                        self._config.client_id, self._config.client_secret
                    ),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
            )
            tok = parse_model(response, OrangeTokenResponse)
            self._cache.set("orange_money", tok.access_token, tok.expires_in)
            return tok.access_token

    async def create_web_payment(
        self,
        amount: str,
        currency: str,
        *,
        order_id: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
        notif_url: str | None = None,
    ) -> dict[str, Any]:
        validated_amount = validate_amount(amount)
        validated_currency = validate_currency(currency)
        for u in (return_url, cancel_url, notif_url):
            if u is not None:
                validate_callback_url(u)
        resolved_notif = notif_url or self._config.notif_url
        resolved_return = return_url or self._config.return_url or resolved_notif
        resolved_cancel = cancel_url or self._config.cancel_url or resolved_notif
        if not resolved_notif or not resolved_return or not resolved_cancel:
            raise ValueError(
                "return_url, cancel_url, and notif_url are required for Orange Money"
            )
        ref = order_id or generate_reference_id()
        response = await self._http.request(
            "POST",
            "/orange-money-webpay/dev/v1/webpayment",
            headers={
                "Authorization": f"Bearer {await self._get_token()}",
                "Content-Type": "application/json",
            },
            json={
                "merchant_key": self._config.merchant_key,
                "currency": validated_currency,
                "order_id": ref,
                "amount": validated_amount,
                "return_url": resolved_return,
                "cancel_url": resolved_cancel,
                "notif_url": resolved_notif,
                "lang": "en",
            },
            product_name="orange_money",
            token_cache=self._cache,
            token_refresher=self._get_token,
        )
        return parse_json_dict(response)

    async def get_transaction_status(
        self, order_id: str, amount: str, pay_token: str
    ) -> dict[str, Any]:
        response = await self._http.request(
            "POST",
            "/orange-money-webpay/dev/v1/transactionstatus",
            headers={
                "Authorization": f"Bearer {await self._get_token()}",
                "Content-Type": "application/json",
            },
            json={
                "order_id": order_id,
                "amount": amount,
                "pay_token": pay_token,
            },
            product_name="orange_money",
            token_cache=self._cache,
            token_refresher=self._get_token,
        )
        return parse_json_dict(response)

    async def close(self) -> None:
        await self._http.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


class OrangeMoneyProvider:
    """Synchronous unified provider adapter for Orange Money."""

    def __init__(self, client: OrangeMoneyClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "orange_money"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _ORANGE_CAPABILITIES

    def collect(self, request: PaymentRequest) -> PaymentResult:
        order_id = (
            request.reference_id or request.external_id or generate_reference_id()
        )
        res = self._client.create_web_payment(
            amount=request.amount,
            currency=request.currency,
            order_id=order_id,
            notif_url=request.callback_url,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=str(res.get("pay_token", order_id)),
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=order_id,
            checkout_url=res.get("payment_url"),
            raw=res,
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        del request
        raise NotImplementedError("Orange Money adapter supports collections only")

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        del kind
        res = self._client.get_transaction_status(reference_id, "0", reference_id)
        return PaymentResult(
            provider=self.name,
            reference_id=reference_id,
            status=_map_orange_status(str(res.get("status", "PENDING"))),
            raw=res,
        )

    def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        del kind
        raise NotImplementedError("Orange Money Web Payment does not expose balances")


class AsyncOrangeMoneyProvider:
    """Asynchronous unified provider adapter for Orange Money."""

    def __init__(self, client: AsyncOrangeMoneyClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "orange_money"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _ORANGE_CAPABILITIES

    async def collect(self, request: PaymentRequest) -> PaymentResult:
        order_id = (
            request.reference_id or request.external_id or generate_reference_id()
        )
        res = await self._client.create_web_payment(
            amount=request.amount,
            currency=request.currency,
            order_id=order_id,
            notif_url=request.callback_url,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=str(res.get("pay_token", order_id)),
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=order_id,
            checkout_url=res.get("payment_url"),
            raw=res,
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        del request
        raise NotImplementedError("Orange Money adapter supports collections only")

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        del kind
        res = await self._client.get_transaction_status(reference_id, "0", reference_id)
        return PaymentResult(
            provider=self.name,
            reference_id=reference_id,
            status=_map_orange_status(str(res.get("status", "PENDING"))),
            raw=res,
        )

    async def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        del kind
        raise NotImplementedError("Orange Money Web Payment does not expose balances")
