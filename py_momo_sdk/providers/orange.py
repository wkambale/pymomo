from __future__ import annotations

import asyncio
import threading
import weakref
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.auth import TokenCache
from py_momo_sdk.exceptions import PyMomoSDKError
from py_momo_sdk.http import (
    DEFAULT_MAX_RESPONSE_BYTES,
    HttpClient,
    parse_json_dict,
    parse_model,
)
from py_momo_sdk.providers.models import (
    BalanceResult,
    DisbursementRequest,
    NormalizedStatus,
    PaymentRequest,
    PaymentResult,
    ProviderCapabilities,
    validate_operation_kind,
)
from py_momo_sdk.telemetry import TelemetryHook
from py_momo_sdk.utils import (
    build_basic_auth_header,
    generate_reference_id,
    validate_amount,
    validate_base_url,
    validate_callback_url,
    validate_currency,
    validate_header_value,
    validate_max_retries,
    validate_request_path,
    validate_retry_backoff,
    validate_timeout,
)

if TYPE_CHECKING:
    from typing_extensions import Self

ORANGE_BASE_URL = "https://api.orange.com"
ORANGE_DEFAULT_API_PATH_PREFIX = "/orange-money-webpay/dev/v1"
_MAX_PAYMENT_CONTEXT = 4096
_VALID_ORANGE_ENVIRONMENTS = frozenset({"sandbox", "production"})
_ORANGE_INTEGER_CURRENCIES = frozenset({"XOF", "XAF", "OUV"})

_ORANGE_CAPABILITIES = ProviderCapabilities(
    provider_id="orange_money",
    supports_collection=True,
    supports_disbursement=False,
    supports_balance=False,
    supports_webhook_hmac=False,
    currencies=("XOF", "XAF", "OUV"),
)


@runtime_checkable
class OrangePaymentContextStore(Protocol):
    """Pluggable store mapping Orange Money ``pay_token`` to ``(order_id, amount, currency)``."""

    def set(self, pay_token: str, order_id: str, amount: str, currency: str) -> None:
        """Persist payment context for a created Orange Money web payment."""

    def get(self, pay_token: str) -> tuple[str, str, str] | None:
        """Look up ``(order_id, amount, currency)`` for a ``pay_token``."""


class _InMemoryOrangeContextStore:
    """Thread-safe bounded in-memory context store for single-process Orange Money flows."""

    def __init__(self, max_entries: int = _MAX_PAYMENT_CONTEXT) -> None:
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self._entries: dict[str, tuple[str, str, str]] = {}

    def set(self, pay_token: str, order_id: str, amount: str, currency: str) -> None:
        with self._lock:
            if (
                pay_token not in self._entries
                and len(self._entries) >= self._max_entries
            ):
                oldest = next(iter(self._entries))
                del self._entries[oldest]
            self._entries[pay_token] = (order_id, amount, currency)

    def get(self, pay_token: str) -> tuple[str, str, str] | None:
        with self._lock:
            return self._entries.get(pay_token)


def _validate_orange_lang(lang: str) -> str:
    if not isinstance(lang, str) or not lang.strip():
        raise ValueError(
            "lang must be a 2-letter ISO language code (e.g. 'fr' or 'en')"
        )
    cleaned = lang.strip().lower()
    if len(cleaned) != 2 or not cleaned.isascii() or not cleaned.isalpha():
        raise ValueError(
            "lang must be a 2-letter ISO language code (e.g. 'fr' or 'en')"
        )
    return cleaned


def _format_orange_amount(amount: str, currency: str | None = None) -> int | str:
    validated = validate_amount(amount)
    dec = Decimal(validated)
    if currency is not None and currency.strip().upper() in _ORANGE_INTEGER_CURRENCIES:
        if dec != dec.to_integral_value():
            raise ValueError(
                f"Orange Money currency {currency.strip().upper()} requires a whole-integer amount"
            )
        return int(dec)
    if dec == dec.to_integral_value():
        return int(dec)
    return validated


@dataclass
class OrangeMoneyConfig:
    """Credentials and settings for Orange Money Web Payment API."""

    client_id: str
    client_secret: str
    merchant_key: str
    return_url: str | None = None
    cancel_url: str | None = None
    notif_url: str | None = None
    environment: str = "sandbox"
    api_path_prefix: str | None = None
    lang: str = "fr"
    reference: str | None = None
    base_url: str = ORANGE_BASE_URL
    timeout: float = 30.0
    max_retries: int = 0
    retry_backoff: float = 0.5
    telemetry: TelemetryHook | None = None

    def __post_init__(self) -> None:
        for fname, fval in (
            ("client_id", self.client_id),
            ("client_secret", self.client_secret),
            ("merchant_key", self.merchant_key),
        ):
            if not isinstance(fval, str) or not fval.strip():
                raise ValueError(f"{fname} must be a non-empty string")
            validate_header_value(fval, field_name=fname)
        if ":" in self.client_id:
            raise ValueError("client_id must not contain ':'")
        if self.environment not in _VALID_ORANGE_ENVIRONMENTS:
            raise ValueError("environment must be 'sandbox' or 'production'")
        self.lang = _validate_orange_lang(self.lang)
        if self.reference is not None:
            if not isinstance(self.reference, str) or not self.reference.strip():
                raise ValueError("reference must not be blank")
            self.reference = validate_header_value(
                self.reference.strip(), field_name="reference"
            )
        if self.return_url is not None:
            validate_callback_url(self.return_url)
        if self.cancel_url is not None:
            validate_callback_url(self.cancel_url)
        if self.notif_url is not None:
            validate_callback_url(self.notif_url)
        if self.api_path_prefix is None:
            if self.environment == "production":
                raise ValueError(
                    "Production Orange Money requires an explicit country api_path_prefix "
                    "(e.g. '/orange-money-webpay/sn/v1')"
                )
            self.api_path_prefix = ORANGE_DEFAULT_API_PATH_PREFIX
        if (
            not isinstance(self.api_path_prefix, str)
            or not self.api_path_prefix.strip()
            or "?" in self.api_path_prefix
        ):
            raise ValueError("api_path_prefix must be a valid URL path prefix")
        cleaned_prefix = self.api_path_prefix.rstrip("/")
        if not cleaned_prefix:
            raise ValueError("api_path_prefix must not be root '/'")
        if (
            self.environment == "production"
            and cleaned_prefix == ORANGE_DEFAULT_API_PATH_PREFIX
        ):
            raise ValueError(
                "Production Orange Money must not use the sandbox '/dev/v1' api_path_prefix"
            )
        validate_request_path(cleaned_prefix)
        self.api_path_prefix = cleaned_prefix
        validate_base_url(self.base_url)
        self.timeout = validate_timeout(self.timeout)
        self.max_retries = validate_max_retries(self.max_retries)
        self.retry_backoff = validate_retry_backoff(self.retry_backoff)

    def __repr__(self) -> str:
        return (
            f"OrangeMoneyConfig(client_secret=<redacted>, "
            f"merchant_key=<redacted>, environment={self.environment!r}, "
            f"base_url={self.base_url!r})"
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
    if norm == "EXPIRED":
        return NormalizedStatus.EXPIRED
    if norm in ("FAILED", "CANCELLED", "CANCELED"):
        return NormalizedStatus.FAILED
    return NormalizedStatus.PENDING


class OrangeMoneyClient:
    """Synchronous Orange Money Web Payment client."""

    def __init__(
        self,
        config: OrangeMoneyConfig,
        *,
        client: httpx.Client | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        telemetry: TelemetryHook | None = None,
        context_store: OrangePaymentContextStore | None = None,
    ) -> None:
        self._config = config
        self._cache = TokenCache()
        self._token_lock = threading.Lock()
        self._context_store: OrangePaymentContextStore = (
            context_store
            if context_store is not None
            else _InMemoryOrangeContextStore()
        )
        self._http = HttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            max_response_bytes=max_response_bytes,
            client=client,
            telemetry=telemetry if telemetry is not None else config.telemetry,
            provider_name="Orange Money",
        )

    def _record_payment_context(
        self, pay_token: str, order_id: str, amount: str, currency: str
    ) -> None:
        self._context_store.set(pay_token, order_id, amount, currency)

    def _lookup_payment_context(self, pay_token: str) -> tuple[str, str, str] | None:
        return self._context_store.get(pay_token)

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
                idempotent=True,
            )
            tok = parse_model(response, OrangeTokenResponse)
            self._cache.set("orange_money", tok.access_token, tok.expires_in)
            return tok.access_token

    def _auth_headers(self, *, reference_id: str | None = None) -> dict[str, str]:
        try:
            token = self._get_token()
        except PyMomoSDKError as exc:
            if exc.reference_id is None and reference_id is not None:
                exc.reference_id = reference_id
            raise
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def create_web_payment(
        self,
        amount: str,
        currency: str,
        *,
        order_id: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
        notif_url: str | None = None,
        lang: str | None = None,
        reference: str | None = None,
    ) -> dict[str, Any]:
        """Initialize an Orange Money web payment session."""
        validated_currency = validate_currency(currency)
        formatted_amount = _format_orange_amount(amount, currency=validated_currency)
        resolved_lang = (
            _validate_orange_lang(lang) if lang is not None else self._config.lang
        )
        resolved_ref_label = (
            reference if reference is not None else self._config.reference
        )
        if resolved_ref_label is not None:
            if (
                not isinstance(resolved_ref_label, str)
                or not resolved_ref_label.strip()
            ):
                raise ValueError("reference must not be blank")
            resolved_ref_label = validate_header_value(
                resolved_ref_label.strip(), field_name="reference"
            )
        for u in (return_url, cancel_url, notif_url):
            if u is not None:
                validate_callback_url(u)
        resolved_notif = notif_url or self._config.notif_url
        resolved_return = return_url or self._config.return_url
        resolved_cancel = cancel_url or self._config.cancel_url
        if not resolved_notif or not resolved_return or not resolved_cancel:
            raise ValueError(
                "return_url, cancel_url, and notif_url are required for Orange Money"
            )
        ref = order_id or generate_reference_id()
        validate_header_value(ref, field_name="order_id")
        payload: dict[str, Any] = {
            "merchant_key": self._config.merchant_key,
            "currency": validated_currency,
            "order_id": ref,
            "amount": formatted_amount,
            "return_url": resolved_return,
            "cancel_url": resolved_cancel,
            "notif_url": resolved_notif,
            "lang": resolved_lang,
        }
        if resolved_ref_label is not None:
            payload["reference"] = resolved_ref_label
        response = self._http.request(
            "POST",
            f"{self._config.api_path_prefix}/webpayment",
            headers=self._auth_headers(reference_id=ref),
            json=payload,
            product_name="orange_money",
            token_cache=self._cache,
            token_refresher=self._get_token,
            reference_id=ref,
        )
        res = parse_json_dict(response, reference_id=ref)
        pay_token = res.get("pay_token")
        if isinstance(pay_token, str) and pay_token.strip():
            self._record_payment_context(
                pay_token.strip(), ref, str(formatted_amount), validated_currency
            )
        return res

    def get_transaction_status(
        self,
        order_id: str,
        amount: str,
        pay_token: str,
        *,
        currency: str | None = None,
    ) -> dict[str, Any]:
        """Check Orange Money transaction status."""
        if not isinstance(order_id, str) or not order_id.strip():
            raise ValueError("order_id must be a non-empty string")
        if not isinstance(pay_token, str) or not pay_token.strip():
            raise ValueError("pay_token must be a non-empty string")
        validate_header_value(order_id, field_name="order_id")
        validate_header_value(pay_token, field_name="pay_token")
        formatted_amount = _format_orange_amount(amount, currency=currency)
        response = self._http.request(
            "POST",
            f"{self._config.api_path_prefix}/transactionstatus",
            headers=self._auth_headers(reference_id=order_id),
            json={
                "order_id": order_id,
                "amount": formatted_amount,
                "pay_token": pay_token,
            },
            product_name="orange_money",
            token_cache=self._cache,
            token_refresher=self._get_token,
            idempotent=True,
            reference_id=order_id,
        )
        return parse_json_dict(response, reference_id=order_id)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncOrangeMoneyClient:
    """Asynchronous Orange Money Web Payment client."""

    def __init__(
        self,
        config: OrangeMoneyConfig,
        *,
        client: httpx.AsyncClient | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        telemetry: TelemetryHook | None = None,
        context_store: OrangePaymentContextStore | None = None,
    ) -> None:
        self._config = config
        self._cache = TokenCache()
        self._loop_locks: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, asyncio.Lock
        ] = weakref.WeakKeyDictionary()
        self._loop_locks_guard = threading.Lock()
        self._context_store: OrangePaymentContextStore = (
            context_store
            if context_store is not None
            else _InMemoryOrangeContextStore()
        )
        self._http = AsyncHttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            max_response_bytes=max_response_bytes,
            client=client,
            telemetry=telemetry if telemetry is not None else config.telemetry,
            provider_name="Orange Money",
        )

    def _get_token_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        with self._loop_locks_guard:
            lock = self._loop_locks.get(loop)
            if lock is None:
                lock = asyncio.Lock()
                self._loop_locks[loop] = lock
            return lock

    def _record_payment_context(
        self, pay_token: str, order_id: str, amount: str, currency: str
    ) -> None:
        self._context_store.set(pay_token, order_id, amount, currency)

    def _lookup_payment_context(self, pay_token: str) -> tuple[str, str, str] | None:
        return self._context_store.get(pay_token)

    async def _get_token(self) -> str:
        cached = self._cache.get("orange_money")
        if cached:
            return cached
        async with self._get_token_lock():
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
                idempotent=True,
            )
            tok = parse_model(response, OrangeTokenResponse)
            self._cache.set("orange_money", tok.access_token, tok.expires_in)
            return tok.access_token

    async def _auth_headers(self, *, reference_id: str | None = None) -> dict[str, str]:
        try:
            token = await self._get_token()
        except PyMomoSDKError as exc:
            if exc.reference_id is None and reference_id is not None:
                exc.reference_id = reference_id
            raise
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def create_web_payment(
        self,
        amount: str,
        currency: str,
        *,
        order_id: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
        notif_url: str | None = None,
        lang: str | None = None,
        reference: str | None = None,
    ) -> dict[str, Any]:
        validated_currency = validate_currency(currency)
        formatted_amount = _format_orange_amount(amount, currency=validated_currency)
        resolved_lang = (
            _validate_orange_lang(lang) if lang is not None else self._config.lang
        )
        resolved_ref_label = (
            reference if reference is not None else self._config.reference
        )
        if resolved_ref_label is not None:
            if (
                not isinstance(resolved_ref_label, str)
                or not resolved_ref_label.strip()
            ):
                raise ValueError("reference must not be blank")
            resolved_ref_label = validate_header_value(
                resolved_ref_label.strip(), field_name="reference"
            )
        for u in (return_url, cancel_url, notif_url):
            if u is not None:
                validate_callback_url(u)
        resolved_notif = notif_url or self._config.notif_url
        resolved_return = return_url or self._config.return_url
        resolved_cancel = cancel_url or self._config.cancel_url
        if not resolved_notif or not resolved_return or not resolved_cancel:
            raise ValueError(
                "return_url, cancel_url, and notif_url are required for Orange Money"
            )
        ref = order_id or generate_reference_id()
        validate_header_value(ref, field_name="order_id")
        payload: dict[str, Any] = {
            "merchant_key": self._config.merchant_key,
            "currency": validated_currency,
            "order_id": ref,
            "amount": formatted_amount,
            "return_url": resolved_return,
            "cancel_url": resolved_cancel,
            "notif_url": resolved_notif,
            "lang": resolved_lang,
        }
        if resolved_ref_label is not None:
            payload["reference"] = resolved_ref_label
        response = await self._http.request(
            "POST",
            f"{self._config.api_path_prefix}/webpayment",
            headers=await self._auth_headers(reference_id=ref),
            json=payload,
            product_name="orange_money",
            token_cache=self._cache,
            token_refresher=self._get_token,
            reference_id=ref,
        )
        res = parse_json_dict(response, reference_id=ref)
        pay_token = res.get("pay_token")
        if isinstance(pay_token, str) and pay_token.strip():
            self._record_payment_context(
                pay_token.strip(), ref, str(formatted_amount), validated_currency
            )
        return res

    async def get_transaction_status(
        self,
        order_id: str,
        amount: str,
        pay_token: str,
        *,
        currency: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(order_id, str) or not order_id.strip():
            raise ValueError("order_id must be a non-empty string")
        if not isinstance(pay_token, str) or not pay_token.strip():
            raise ValueError("pay_token must be a non-empty string")
        validate_header_value(order_id, field_name="order_id")
        validate_header_value(pay_token, field_name="pay_token")
        formatted_amount = _format_orange_amount(amount, currency=currency)
        response = await self._http.request(
            "POST",
            f"{self._config.api_path_prefix}/transactionstatus",
            headers=await self._auth_headers(reference_id=order_id),
            json={
                "order_id": order_id,
                "amount": formatted_amount,
                "pay_token": pay_token,
            },
            product_name="orange_money",
            token_cache=self._cache,
            token_refresher=self._get_token,
            idempotent=True,
            reference_id=order_id,
        )
        return parse_json_dict(response, reference_id=order_id)

    async def close(self) -> None:
        await self._http.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


def _extract_orange_pay_token(res: dict[str, Any]) -> str:
    raw = res.get("pay_token")
    if not isinstance(raw, str) or not raw.strip():
        msg = res.get("message") or res.get("description")
        detail = f": {msg}" if isinstance(msg, str) and msg.strip() else ""
        raise PyMomoSDKError(f"Orange Money response missing 'pay_token'{detail}")
    return raw.strip()


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
        pay_token = _extract_orange_pay_token(res)
        return PaymentResult(
            provider=self.name,
            reference_id=pay_token,
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
        self,
        reference_id: str,
        *,
        kind: str = "collection",
        order_id: str | None = None,
        amount: str | None = None,
        currency: str | None = None,
    ) -> PaymentResult:
        validate_operation_kind(kind)
        if kind == "disbursement":
            raise NotImplementedError("Orange Money adapter supports collections only")
        resolved_order_id = order_id
        resolved_amount = amount
        resolved_currency = currency
        if resolved_order_id is None or resolved_amount is None:
            ctx = self._client._lookup_payment_context(reference_id)
            if ctx is None:
                raise PyMomoSDKError(
                    "Orange Money status queries require order_id and amount; "
                    "pass order_id=... and amount=... or configure a shared context_store"
                )
            ctx_order_id, ctx_amount, ctx_currency = ctx
            resolved_order_id = resolved_order_id or ctx_order_id
            resolved_amount = resolved_amount or ctx_amount
            resolved_currency = resolved_currency or ctx_currency
        res = self._client.get_transaction_status(
            resolved_order_id,
            resolved_amount,
            reference_id,
            currency=resolved_currency,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=reference_id,
            status=_map_orange_status(str(res.get("status", "PENDING"))),
            amount=resolved_amount,
            currency=resolved_currency,
            external_id=resolved_order_id,
            raw=res,
        )

    def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        del currency
        validate_operation_kind(kind)
        raise NotImplementedError("Orange Money Web Payment does not expose balances")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


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
        pay_token = _extract_orange_pay_token(res)
        return PaymentResult(
            provider=self.name,
            reference_id=pay_token,
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
        self,
        reference_id: str,
        *,
        kind: str = "collection",
        order_id: str | None = None,
        amount: str | None = None,
        currency: str | None = None,
    ) -> PaymentResult:
        validate_operation_kind(kind)
        if kind == "disbursement":
            raise NotImplementedError("Orange Money adapter supports collections only")
        resolved_order_id = order_id
        resolved_amount = amount
        resolved_currency = currency
        if resolved_order_id is None or resolved_amount is None:
            ctx = self._client._lookup_payment_context(reference_id)
            if ctx is None:
                raise PyMomoSDKError(
                    "Orange Money status queries require order_id and amount; "
                    "pass order_id=... and amount=... or configure a shared context_store"
                )
            ctx_order_id, ctx_amount, ctx_currency = ctx
            resolved_order_id = resolved_order_id or ctx_order_id
            resolved_amount = resolved_amount or ctx_amount
            resolved_currency = resolved_currency or ctx_currency
        res = await self._client.get_transaction_status(
            resolved_order_id,
            resolved_amount,
            reference_id,
            currency=resolved_currency,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=reference_id,
            status=_map_orange_status(str(res.get("status", "PENDING"))),
            amount=resolved_amount,
            currency=resolved_currency,
            external_id=resolved_order_id,
            raw=res,
        )

    async def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        del currency
        validate_operation_kind(kind)
        raise NotImplementedError("Orange Money Web Payment does not expose balances")

    async def aclose(self) -> None:
        await self._client.close()

    async def close(self) -> None:
        await self.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
