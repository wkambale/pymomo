from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel, ConfigDict, Field

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
)
from py_momo_sdk.utils import (
    normalise_msisdn,
    validate_callback_url,
    validate_header_value,
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


@dataclass
class MpesaConfig:
    """Credentials and settings for Safaricom M-Pesa Daraja API."""

    consumer_key: str
    consumer_secret: str
    short_code: str
    passkey: str
    callback_url: str = "https://example.com/mpesa/callback"
    initiator_name: str = "testapi"
    security_credential: str | None = None
    environment: str = "sandbox"
    base_url: str | None = None
    timeout: float = 30.0
    max_retries: int = 0

    def __post_init__(self) -> None:
        validate_header_value(self.consumer_key, field_name="consumer_key")
        validate_header_value(self.consumer_secret, field_name="consumer_secret")
        validate_header_value(self.short_code, field_name="short_code")
        validate_header_value(self.passkey, field_name="passkey")
        validate_callback_url(self.callback_url)
        self.timeout = validate_timeout(self.timeout)
        if self.base_url is None:
            self.base_url = (
                MPESA_SANDBOX_BASE_URL
                if self.environment == "sandbox"
                else MPESA_PRODUCTION_BASE_URL
            )

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
    expires_in: str | int


class MpesaStkPushResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    merchant_request_id: str = Field(default="", alias="MerchantRequestID")
    checkout_request_id: str = Field(default="", alias="CheckoutRequestID")
    response_code: str = Field(default="", alias="ResponseCode")
    response_description: str = Field(default="", alias="ResponseDescription")


class MpesaStkQueryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    checkout_request_id: str = Field(default="", alias="CheckoutRequestID")
    result_code: str | int = Field(default="", alias="ResultCode")
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


def _build_basic_token_header(key: str, secret: str) -> str:
    raw = f"{key}:{secret}".encode()
    return f"Basic {base64.b64encode(raw).decode('ascii')}"


class MpesaClient:
    """Synchronous Safaricom M-Pesa Daraja API client."""

    def __init__(
        self, config: MpesaConfig, *, client: httpx.Client | None = None
    ) -> None:
        self._config = config
        self._cache = TokenCache()
        self._http = HttpClient(
            base_url=config.base_url or MPESA_SANDBOX_BASE_URL,
            timeout=config.timeout,
            max_retries=config.max_retries,
            client=client,
        )

    def _get_token(self) -> str:
        cached = self._cache.get("mpesa")
        if cached:
            return cached
        response = self._http.request(
            "GET",
            "/oauth/v1/generate?grant_type=client_credentials",
            headers={
                "Authorization": _build_basic_token_header(
                    self._config.consumer_key, self._config.consumer_secret
                )
            },
        )
        token_resp = parse_model(response, MpesaTokenResponse)
        self._cache.set("mpesa", token_resp.access_token, int(token_resp.expires_in))
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
                "Amount": amount,
                "PartyA": msisdn,
                "PartyB": self._config.short_code,
                "PhoneNumber": msisdn,
                "CallBackURL": callback_url or self._config.callback_url,
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
        if not self._config.security_credential:
            raise ValueError("security_credential is required for M-Pesa B2C payouts")
        msisdn = normalise_msisdn(phone_number)
        cb = callback_url or self._config.callback_url
        response = self._http.request(
            "POST",
            "/mpesa/b2c/v3/paymentrequest",
            headers=self._auth_headers(),
            json={
                "InitiatorName": self._config.initiator_name,
                "SecurityCredential": self._config.security_credential,
                "CommandID": "BusinessPayment",
                "Amount": amount,
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
        self._http = AsyncHttpClient(
            base_url=config.base_url or MPESA_SANDBOX_BASE_URL,
            timeout=config.timeout,
            max_retries=config.max_retries,
            client=client,
        )

    async def _get_token(self) -> str:
        cached = self._cache.get("mpesa")
        if cached:
            return cached
        response = await self._http.request(
            "GET",
            "/oauth/v1/generate?grant_type=client_credentials",
            headers={
                "Authorization": _build_basic_token_header(
                    self._config.consumer_key, self._config.consumer_secret
                )
            },
        )
        token_resp = parse_model(response, MpesaTokenResponse)
        self._cache.set("mpesa", token_resp.access_token, int(token_resp.expires_in))
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
                "Amount": amount,
                "PartyA": msisdn,
                "PartyB": self._config.short_code,
                "PhoneNumber": msisdn,
                "CallBackURL": callback_url or self._config.callback_url,
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
        if not self._config.security_credential:
            raise ValueError("security_credential is required for M-Pesa B2C payouts")
        msisdn = normalise_msisdn(phone_number)
        cb = callback_url or self._config.callback_url
        response = await self._http.request(
            "POST",
            "/mpesa/b2c/v3/paymentrequest",
            headers=await self._auth_headers(),
            json={
                "InitiatorName": self._config.initiator_name,
                "SecurityCredential": self._config.security_credential,
                "CommandID": "BusinessPayment",
                "Amount": amount,
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
    code = str(result.result_code)
    status = (
        NormalizedStatus.SUCCEEDED
        if code == "0"
        else NormalizedStatus.FAILED if code else NormalizedStatus.PENDING
    )
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
            reason=res.response_description or None,
            raw=res.model_dump(mode="json"),
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        res = self._client.b2c_transfer(
            amount=request.amount,
            phone_number=request.payee_msisdn,
            remarks=request.payer_message or "Payout",
            occasion=request.external_id or "Payout",
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
            reason=res.response_description or None,
            raw=res.model_dump(mode="json"),
        )

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        del kind
        return _map_mpesa_query(reference_id, self._client.stk_query(reference_id))

    def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        del kind
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
            reason=res.response_description or None,
            raw=res.model_dump(mode="json"),
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        res = await self._client.b2c_transfer(
            amount=request.amount,
            phone_number=request.payee_msisdn,
            remarks=request.payer_message or "Payout",
            occasion=request.external_id or "Payout",
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
            reason=res.response_description or None,
            raw=res.model_dump(mode="json"),
        )

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        del kind
        res = await self._client.stk_query(reference_id)
        return _map_mpesa_query(reference_id, res)

    async def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        del kind
        raise NotImplementedError("M-Pesa balance queries use asynchronous callbacks")
