from __future__ import annotations

import asyncio
import base64
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.auth import TokenCache
from py_momo_sdk.http import HttpClient, parse_model
from py_momo_sdk.providers.models import (
    BalanceResult,
    DisbursementRequest,
    NormalizedStatus,
    PaymentRequest,
    PaymentResult,
    ProviderCapabilities,
    validate_operation_kind,
)
from py_momo_sdk.utils import (
    build_basic_auth_header,
    normalise_msisdn,
    validate_amount,
    validate_base_url,
    validate_callback_url,
    validate_header_value,
    validate_max_retries,
    validate_retry_backoff,
    validate_timeout,
)

if TYPE_CHECKING:
    from typing_extensions import Self

MPESA_SANDBOX_BASE_URL = "https://sandbox.safaricom.co.ke"
MPESA_PRODUCTION_BASE_URL = "https://api.safaricom.co.ke"

_MPESA_CAPABILITIES = ProviderCapabilities(
    provider_id="mpesa",
    supports_collection=True,
    supports_disbursement=True,
    supports_balance=False,
    supports_webhook_hmac=False,
    currencies=("KES", "TZS", "ETB", "CDF"),
)


_VALID_MPESA_ENVIRONMENTS = frozenset({"sandbox", "production"})


@dataclass
class MpesaConfig:
    """Credentials and settings for Safaricom M-Pesa Daraja API."""

    consumer_key: str
    consumer_secret: str
    short_code: str
    passkey: str
    callback_url: str | None = None
    initiator_name: str | None = None
    security_credential: str | None = None
    environment: str = "sandbox"
    base_url: str | None = None
    timeout: float = 30.0
    max_retries: int = 0
    retry_backoff: float = 0.5

    def __post_init__(self) -> None:
        for fname, fval in (
            ("consumer_key", self.consumer_key),
            ("consumer_secret", self.consumer_secret),
            ("short_code", self.short_code),
            ("passkey", self.passkey),
        ):
            if not isinstance(fval, str) or not fval.strip():
                raise ValueError(f"{fname} must be a non-empty string")
            validate_header_value(fval, field_name=fname)
        if ":" in self.consumer_key:
            raise ValueError("consumer_key must not contain ':'")
        if self.environment not in _VALID_MPESA_ENVIRONMENTS:
            raise ValueError("environment must be 'sandbox' or 'production'")
        allow_localhost = self.environment == "sandbox"
        if self.callback_url is not None:
            validate_callback_url(self.callback_url, allow_localhost=allow_localhost)
        if self.initiator_name is None and self.environment == "sandbox":
            self.initiator_name = "testapi"
        if self.initiator_name is not None:
            if not self.initiator_name.strip():
                raise ValueError("initiator_name must not be blank")
            validate_header_value(self.initiator_name, field_name="initiator_name")
        if self.security_credential is not None:
            if not self.security_credential.strip():
                raise ValueError("security_credential must not be blank")
            validate_header_value(
                self.security_credential, field_name="security_credential"
            )
        self.timeout = validate_timeout(self.timeout)
        self.max_retries = validate_max_retries(self.max_retries)
        self.retry_backoff = validate_retry_backoff(self.retry_backoff)
        if self.base_url is None:
            self.base_url = (
                MPESA_SANDBOX_BASE_URL
                if self.environment == "sandbox"
                else MPESA_PRODUCTION_BASE_URL
            )
        else:
            validate_base_url(self.base_url, allow_localhost=allow_localhost)

    def __repr__(self) -> str:
        return (
            f"MpesaConfig(short_code={self.short_code!r}, "
            f"consumer_key=<redacted>, consumer_secret=<redacted>, "
            f"passkey=<redacted>, environment={self.environment!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class MpesaTokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str
    expires_in: int = Field(gt=0)

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
        return f"MpesaTokenResponse(access_token=<redacted>, expires_in={self.expires_in!r})"

    def __str__(self) -> str:
        return self.__repr__()


class MpesaStkPushResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    merchant_request_id: str = Field(default="", alias="MerchantRequestID")
    checkout_request_id: str = Field(default="", alias="CheckoutRequestID")
    response_code: str = Field(default="", alias="ResponseCode")
    response_description: str = Field(default="", alias="ResponseDescription")


class MpesaStkQueryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    checkout_request_id: str = Field(default="", alias="CheckoutRequestID")
    result_code: str | int | None = Field(default=None, alias="ResultCode")
    result_desc: str = Field(default="", alias="ResultDesc")


class MpesaB2CResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conversation_id: str = Field(default="", alias="ConversationID")
    originator_conversation_id: str = Field(
        default="", alias="OriginatorConversationID"
    )
    response_code: str = Field(default="", alias="ResponseCode")
    response_description: str = Field(default="", alias="ResponseDescription")


def _build_stk_password(short_code: str, passkey: str) -> tuple[str, str]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    raw = f"{short_code}{passkey}{timestamp}".encode()
    return base64.b64encode(raw).decode("ascii"), timestamp


class MpesaClient:
    """Synchronous Safaricom M-Pesa Daraja API client."""

    def __init__(
        self, config: MpesaConfig, *, client: httpx.Client | None = None
    ) -> None:
        self._config = config
        self._cache = TokenCache()
        self._token_lock = threading.Lock()
        self._http = HttpClient(
            base_url=config.base_url or MPESA_SANDBOX_BASE_URL,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            client=client,
            provider_name="M-Pesa",
        )

    def _get_token(self) -> str:
        cached = self._cache.get("mpesa")
        if cached:
            return cached
        with self._token_lock:
            cached = self._cache.get("mpesa")
            if cached:
                return cached
            response = self._http.request(
                "GET",
                "/oauth/v1/generate?grant_type=client_credentials",
                headers={
                    "Authorization": build_basic_auth_header(
                        self._config.consumer_key, self._config.consumer_secret
                    )
                },
            )
            token_resp = parse_model(response, MpesaTokenResponse)
            self._cache.set("mpesa", token_resp.access_token, token_resp.expires_in)
            return token_resp.access_token

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def stk_push(
        self,
        amount: str,
        phone_number: str,
        *,
        account_reference: str = "Payment",
        transaction_desc: str = "Payment",
        callback_url: str | None = None,
    ) -> MpesaStkPushResponse:
        """Initiate an M-Pesa STK Push (Lipa Na M-Pesa Online) prompt."""
        validated_amount = validate_amount(amount)
        if callback_url is not None:
            validate_callback_url(callback_url)
        cb = callback_url or self._config.callback_url
        if not cb:
            raise ValueError("callback_url is required for M-Pesa STK Push")
        password, timestamp = _build_stk_password(
            self._config.short_code, self._config.passkey
        )
        msisdn = normalise_msisdn(phone_number)
        response = self._http.request(
            "POST",
            "/mpesa/stkpush/v1/processrequest",
            headers=self._auth_headers(),
            json={
                "BusinessShortCode": self._config.short_code,
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": validated_amount,
                "PartyA": msisdn,
                "PartyB": self._config.short_code,
                "PhoneNumber": msisdn,
                "CallBackURL": cb,
                "AccountReference": account_reference,
                "TransactionDesc": transaction_desc,
            },
            product_name="mpesa",
            token_cache=self._cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, MpesaStkPushResponse)

    def stk_query(self, checkout_request_id: str) -> MpesaStkQueryResponse:
        """Query the status of an STK Push transaction."""
        password, timestamp = _build_stk_password(
            self._config.short_code, self._config.passkey
        )
        response = self._http.request(
            "POST",
            "/mpesa/stkpushquery/v1/query",
            headers=self._auth_headers(),
            json={
                "BusinessShortCode": self._config.short_code,
                "Password": password,
                "Timestamp": timestamp,
                "CheckoutRequestID": checkout_request_id,
            },
            product_name="mpesa",
            token_cache=self._cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, MpesaStkQueryResponse)

    def b2c_transfer(
        self,
        amount: str,
        phone_number: str,
        *,
        remarks: str = "Payout",
        occasion: str = "Payout",
        callback_url: str | None = None,
    ) -> MpesaB2CResponse:
        """Initiate an M-Pesa B2C disbursement payout."""
        validated_amount = validate_amount(amount)
        if not self._config.security_credential:
            raise ValueError("security_credential is required for M-Pesa B2C payouts")
        if not self._config.initiator_name:
            raise ValueError("initiator_name is required for M-Pesa B2C payouts")
        if callback_url is not None:
            validate_callback_url(callback_url)
        cb = callback_url or self._config.callback_url
        if not cb:
            raise ValueError("callback_url is required for M-Pesa B2C payouts")
        msisdn = normalise_msisdn(phone_number)
        response = self._http.request(
            "POST",
            "/mpesa/b2c/v3/paymentrequest",
            headers=self._auth_headers(),
            json={
                "InitiatorName": self._config.initiator_name,
                "SecurityCredential": self._config.security_credential,
                "CommandID": "BusinessPayment",
                "Amount": validated_amount,
                "PartyA": self._config.short_code,
                "PartyB": msisdn,
                "Remarks": remarks,
                "QueueTimeOutURL": cb,
                "ResultURL": cb,
                "Occasion": occasion,
            },
            product_name="mpesa",
            token_cache=self._cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, MpesaB2CResponse)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncMpesaClient:
    """Asynchronous Safaricom M-Pesa Daraja API client."""

    def __init__(
        self, config: MpesaConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._config = config
        self._cache = TokenCache()
        self._token_lock = asyncio.Lock()
        self._http = AsyncHttpClient(
            base_url=config.base_url or MPESA_SANDBOX_BASE_URL,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            client=client,
            provider_name="M-Pesa",
        )

    async def _get_token(self) -> str:
        cached = self._cache.get("mpesa")
        if cached:
            return cached
        async with self._token_lock:
            cached = self._cache.get("mpesa")
            if cached:
                return cached
            response = await self._http.request(
                "GET",
                "/oauth/v1/generate?grant_type=client_credentials",
                headers={
                    "Authorization": build_basic_auth_header(
                        self._config.consumer_key, self._config.consumer_secret
                    )
                },
            )
            token_resp = parse_model(response, MpesaTokenResponse)
            self._cache.set("mpesa", token_resp.access_token, token_resp.expires_in)
            return token_resp.access_token

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def stk_push(
        self,
        amount: str,
        phone_number: str,
        *,
        account_reference: str = "Payment",
        transaction_desc: str = "Payment",
        callback_url: str | None = None,
    ) -> MpesaStkPushResponse:
        validated_amount = validate_amount(amount)
        if callback_url is not None:
            validate_callback_url(callback_url)
        cb = callback_url or self._config.callback_url
        if not cb:
            raise ValueError("callback_url is required for M-Pesa STK Push")
        password, timestamp = _build_stk_password(
            self._config.short_code, self._config.passkey
        )
        msisdn = normalise_msisdn(phone_number)
        response = await self._http.request(
            "POST",
            "/mpesa/stkpush/v1/processrequest",
            headers=await self._auth_headers(),
            json={
                "BusinessShortCode": self._config.short_code,
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": validated_amount,
                "PartyA": msisdn,
                "PartyB": self._config.short_code,
                "PhoneNumber": msisdn,
                "CallBackURL": cb,
                "AccountReference": account_reference,
                "TransactionDesc": transaction_desc,
            },
            product_name="mpesa",
            token_cache=self._cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, MpesaStkPushResponse)

    async def stk_query(self, checkout_request_id: str) -> MpesaStkQueryResponse:
        password, timestamp = _build_stk_password(
            self._config.short_code, self._config.passkey
        )
        response = await self._http.request(
            "POST",
            "/mpesa/stkpushquery/v1/query",
            headers=await self._auth_headers(),
            json={
                "BusinessShortCode": self._config.short_code,
                "Password": password,
                "Timestamp": timestamp,
                "CheckoutRequestID": checkout_request_id,
            },
            product_name="mpesa",
            token_cache=self._cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, MpesaStkQueryResponse)

    async def b2c_transfer(
        self,
        amount: str,
        phone_number: str,
        *,
        remarks: str = "Payout",
        occasion: str = "Payout",
        callback_url: str | None = None,
    ) -> MpesaB2CResponse:
        validated_amount = validate_amount(amount)
        if not self._config.security_credential:
            raise ValueError("security_credential is required for M-Pesa B2C payouts")
        if not self._config.initiator_name:
            raise ValueError("initiator_name is required for M-Pesa B2C payouts")
        if callback_url is not None:
            validate_callback_url(callback_url)
        cb = callback_url or self._config.callback_url
        if not cb:
            raise ValueError("callback_url is required for M-Pesa B2C payouts")
        msisdn = normalise_msisdn(phone_number)
        response = await self._http.request(
            "POST",
            "/mpesa/b2c/v3/paymentrequest",
            headers=await self._auth_headers(),
            json={
                "InitiatorName": self._config.initiator_name,
                "SecurityCredential": self._config.security_credential,
                "CommandID": "BusinessPayment",
                "Amount": validated_amount,
                "PartyA": self._config.short_code,
                "PartyB": msisdn,
                "Remarks": remarks,
                "QueueTimeOutURL": cb,
                "ResultURL": cb,
                "Occasion": occasion,
            },
            product_name="mpesa",
            token_cache=self._cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, MpesaB2CResponse)

    async def close(self) -> None:
        await self._http.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


def _map_mpesa_query(reference_id: str, result: MpesaStkQueryResponse) -> PaymentResult:
    code = "" if result.result_code is None else str(result.result_code).strip()
    if not code:
        status = NormalizedStatus.PENDING
    elif code == "0":
        status = NormalizedStatus.SUCCEEDED
    else:
        status = NormalizedStatus.FAILED
    return PaymentResult(
        provider="mpesa",
        reference_id=reference_id,
        status=status,
        reason=result.result_desc or None,
        raw=result.model_dump(mode="json"),
    )


class MpesaProvider:
    """Synchronous unified provider adapter for Safaricom M-Pesa."""

    def __init__(self, client: MpesaClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "mpesa"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _MPESA_CAPABILITIES

    def collect(self, request: PaymentRequest) -> PaymentResult:
        res = self._client.stk_push(
            amount=request.amount,
            phone_number=request.payer_msisdn,
            account_reference=request.external_id or "Payment",
            transaction_desc=request.payer_message or "Payment",
            callback_url=request.callback_url,
        )
        status = (
            NormalizedStatus.PENDING
            if res.response_code == "0"
            else NormalizedStatus.FAILED
        )
        return PaymentResult(
            provider=self.name,
            reference_id=res.checkout_request_id or res.merchant_request_id,
            status=status,
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or None,
            reason=res.response_description or None,
            raw=res.model_dump(mode="json"),
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        res = self._client.b2c_transfer(
            amount=request.amount,
            phone_number=request.payee_msisdn,
            remarks=request.payer_message or "Payout",
            occasion=request.external_id or "Payout",
            callback_url=request.callback_url,
        )
        status = (
            NormalizedStatus.PENDING
            if res.response_code == "0"
            else NormalizedStatus.FAILED
        )
        return PaymentResult(
            provider=self.name,
            reference_id=res.conversation_id or res.originator_conversation_id,
            status=status,
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or None,
            reason=res.response_description or None,
            raw=res.model_dump(mode="json"),
        )

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        if kind == "disbursement":
            raise NotImplementedError(
                "M-Pesa B2C disbursement status uses asynchronous ResultURL callbacks"
            )
        return _map_mpesa_query(reference_id, self._client.stk_query(reference_id))

    def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        validate_operation_kind(kind)
        raise NotImplementedError("M-Pesa balance queries use asynchronous callbacks")


class AsyncMpesaProvider:
    """Asynchronous unified provider adapter for Safaricom M-Pesa."""

    def __init__(self, client: AsyncMpesaClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "mpesa"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _MPESA_CAPABILITIES

    async def collect(self, request: PaymentRequest) -> PaymentResult:
        res = await self._client.stk_push(
            amount=request.amount,
            phone_number=request.payer_msisdn,
            account_reference=request.external_id or "Payment",
            transaction_desc=request.payer_message or "Payment",
            callback_url=request.callback_url,
        )
        status = (
            NormalizedStatus.PENDING
            if res.response_code == "0"
            else NormalizedStatus.FAILED
        )
        return PaymentResult(
            provider=self.name,
            reference_id=res.checkout_request_id or res.merchant_request_id,
            status=status,
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or None,
            reason=res.response_description or None,
            raw=res.model_dump(mode="json"),
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        res = await self._client.b2c_transfer(
            amount=request.amount,
            phone_number=request.payee_msisdn,
            remarks=request.payer_message or "Payout",
            occasion=request.external_id or "Payout",
            callback_url=request.callback_url,
        )
        status = (
            NormalizedStatus.PENDING
            if res.response_code == "0"
            else NormalizedStatus.FAILED
        )
        return PaymentResult(
            provider=self.name,
            reference_id=res.conversation_id or res.originator_conversation_id,
            status=status,
            amount=request.amount,
            currency=request.currency,
            external_id=request.external_id or None,
            reason=res.response_description or None,
            raw=res.model_dump(mode="json"),
        )

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        if kind == "disbursement":
            raise NotImplementedError(
                "M-Pesa B2C disbursement status uses asynchronous ResultURL callbacks"
            )
        res = await self._client.stk_query(reference_id)
        return _map_mpesa_query(reference_id, res)

    async def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        validate_operation_kind(kind)
        raise NotImplementedError("M-Pesa balance queries use asynchronous callbacks")
