from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import quote

import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from py_momo_sdk._async.http import AsyncHttpClient
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
from py_momo_sdk.webhooks import WebhookHandler

if TYPE_CHECKING:
    from typing_extensions import Self

WAVE_BASE_URL = "https://api.wave.com"
_VALID_WAVE_ENVIRONMENTS = frozenset({"sandbox", "production"})


def _is_wave_live_key(api_key: str) -> bool:
    return "_prod_" in api_key.lower()


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
    signing_secret: str | None = None
    success_url: str | None = None
    error_url: str | None = None
    base_url: str = WAVE_BASE_URL
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
        return not _is_wave_live_key(self.api_key)

    def __post_init__(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        validate_header_value(self.api_key, field_name="api_key")
        if (
            self.environment is not None
            and self.environment not in _VALID_WAVE_ENVIRONMENTS
        ):
            raise ValueError("environment must be 'sandbox' or 'production'")
        if self.environment == "sandbox" and _is_wave_live_key(self.api_key):
            raise ValueError(
                "Live Wave API key must not be used in sandbox environment"
            )
        if self.webhook_secret is not None:
            if (
                not isinstance(self.webhook_secret, str)
                or not self.webhook_secret.strip()
            ):
                raise ValueError("webhook_secret must not be blank")
            validate_header_value(self.webhook_secret, field_name="webhook_secret")
        if self.signing_secret is not None:
            if (
                not isinstance(self.signing_secret, str)
                or not self.signing_secret.strip()
            ):
                raise ValueError("signing_secret must not be blank")
            validate_header_value(self.signing_secret, field_name="signing_secret")
        allow_localhost = self.allow_localhost
        if self.success_url is not None:
            validate_callback_url(self.success_url, allow_localhost=allow_localhost)
        if self.error_url is not None:
            validate_callback_url(self.error_url, allow_localhost=allow_localhost)
        validate_base_url(self.base_url, allow_localhost=allow_localhost)
        self.timeout = validate_timeout(self.timeout)
        self.max_retries = validate_max_retries(self.max_retries)
        self.retry_backoff = validate_retry_backoff(self.retry_backoff)

    def __repr__(self) -> str:
        return (
            f"WaveConfig(api_key=<redacted>, webhook_secret=<redacted>, "
            f"signing_secret=<redacted>, base_url={self.base_url!r}, "
            f"timeout={self.timeout!r})"
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
    transaction_id: str | None = None
    when_completed: str | None = None
    last_payment_error: dict[str, Any] | str | None = None


class WavePayoutResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    receive_amount: str = Field(
        validation_alias=AliasChoices("receive_amount", "amount")
    )
    currency: str
    status: str = "processing"
    client_reference: str | None = None
    transaction_id: str | None = None
    when_completed: str | None = None
    payout_error: dict[str, Any] | str | None = None

    @property
    def amount(self) -> str:
        """Backward-compatible alias for ``receive_amount``."""
        return self.receive_amount


def _extract_wave_error(err: dict[str, Any] | str | None) -> str | None:
    if err is None:
        return None
    if isinstance(err, str):
        return err.strip() or None
    if isinstance(err, dict):
        code = err.get("code")
        msg = err.get("message")
        if code and msg:
            return f"{code}: {msg}"
        if msg:
            return str(msg)
        if code:
            return str(code)
    return None


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
    if normalized in ("reversed",):
        return NormalizedStatus.REVERSED
    if normalized in ("cancelled", "canceled", "failed"):
        return NormalizedStatus.FAILED
    return NormalizedStatus.PENDING


_WAVE_DEFAULT_MAX_FUTURE_SKEW_SECONDS = 30.0
_WaveModelT = TypeVar("_WaveModelT", bound=BaseModel)


def _sign_wave_request(
    body: bytes, secret: str, *, timestamp: int | None = None
) -> str:
    """Compute a Wave ``Wave-Signature`` header (``t=<ts>,v1=<hex>``) over raw body bytes."""
    ts = int(time.time()) if timestamp is None else int(timestamp)
    signed_payload = str(ts).encode("ascii") + body
    digest = hmac.new(
        secret.encode("utf-8"), signed_payload, hashlib.sha256
    ).hexdigest()
    return f"t={ts},v1={digest}"


def _encode_wave_query_ref(client_reference: str) -> str:
    if not isinstance(client_reference, str) or not client_reference.strip():
        raise ValueError("client_reference must be a non-empty string")
    cleaned = validate_header_value(
        client_reference.strip(), field_name="client_reference"
    )
    return quote(cleaned, safe="")


def _parse_optional_json_dict(
    response: httpx.Response, *, reference_id: str | None = None
) -> dict[str, Any]:
    if not response.content or not response.content.strip():
        return {}
    return parse_json_dict(response, reference_id=reference_id)


def _parse_wave_search_results(
    res: dict[str, Any],
    model_cls: type[_WaveModelT],
    *,
    reference_id: str | None = None,
) -> list[_WaveModelT]:
    items = res.get("result")
    if not isinstance(items, list):
        raise PyMomoSDKError(
            "Malformed Wave search response: expected list in 'result'",
            reference_id=reference_id,
            provider="Wave",
        )
    parsed: list[_WaveModelT] = []
    for item in items:
        if not isinstance(item, dict):
            raise PyMomoSDKError(
                "Malformed Wave search response item",
                reference_id=reference_id,
                provider="Wave",
            )
        try:
            parsed.append(model_cls.model_validate(item))
        except ValidationError as exc:
            raise PyMomoSDKError(
                f"Malformed Wave {model_cls.__name__} item in search response",
                reference_id=reference_id,
                provider="Wave",
            ) from exc
    return parsed


def _map_wave_session_status(session: WaveCheckoutSession) -> NormalizedStatus:
    mapped = _map_wave_status(session.payment_status)
    if mapped in (NormalizedStatus.SUCCEEDED, NormalizedStatus.REVERSED):
        return mapped
    if session.checkout_status.strip().lower() == "expired":
        return NormalizedStatus.EXPIRED
    return mapped


class WaveClient:
    """Synchronous Wave Mobile Money client."""

    def __init__(
        self,
        config: WaveConfig,
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
            provider_name="Wave",
            allow_localhost=config.allow_localhost,
        )

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            validate_header_value(idempotency_key, field_name="client_reference")
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def create_checkout_session(
        self,
        amount: str,
        currency: str,
        *,
        client_reference: str | None = None,
        success_url: str | None = None,
        error_url: str | None = None,
        restrict_payer_mobile: str | None = None,
    ) -> WaveCheckoutSession:
        """Create a Wave checkout session."""
        validated_amount = validate_amount(amount)
        validated_currency = validate_currency(currency)
        if success_url is not None:
            validate_callback_url(
                success_url, allow_localhost=self._config.allow_localhost
            )
        if error_url is not None:
            validate_callback_url(
                error_url, allow_localhost=self._config.allow_localhost
            )
        resolved_success = success_url or self._config.success_url
        resolved_error = error_url or self._config.error_url
        if not resolved_success or not resolved_error:
            raise ValueError(
                "success_url and error_url are required for Wave checkout sessions"
            )
        ref = client_reference or generate_reference_id()
        payload: dict[str, Any] = {
            "amount": validated_amount,
            "currency": validated_currency,
            "success_url": resolved_success,
            "error_url": resolved_error,
            "client_reference": ref,
        }
        if restrict_payer_mobile is not None:
            payload["restrict_payer_mobile"] = (
                f"+{normalise_msisdn(restrict_payer_mobile)}"
            )
        response = self._http.request(
            "POST",
            "/v1/checkout/sessions",
            headers=self._headers(idempotency_key=ref),
            json=payload,
            idempotent=True,
            reference_id=ref,
        )
        return parse_model(response, WaveCheckoutSession, reference_id=ref)

    def get_checkout_session(self, session_id: str) -> WaveCheckoutSession:
        """Retrieve a Wave checkout session by ID."""
        encoded = encode_path_segment(session_id, field_name="session_id")
        response = self._http.request(
            "GET",
            f"/v1/checkout/sessions/{encoded}",
            headers=self._headers(),
            reference_id=session_id,
        )
        return parse_model(response, WaveCheckoutSession, reference_id=session_id)

    def refund_checkout_session(self, session_id: str) -> dict[str, Any]:
        """Refund a completed Wave checkout session (``POST /v1/checkout/sessions/{id}/refund``)."""
        encoded = encode_path_segment(session_id, field_name="session_id")
        response = self._http.request(
            "POST",
            f"/v1/checkout/sessions/{encoded}/refund",
            headers=self._headers(),
            idempotent=False,
            reference_id=session_id,
        )
        return _parse_optional_json_dict(response, reference_id=session_id)

    def expire_checkout_session(self, session_id: str) -> dict[str, Any]:
        """Expire an open Wave checkout session (``POST /v1/checkout/sessions/{id}/expire``)."""
        encoded = encode_path_segment(session_id, field_name="session_id")
        response = self._http.request(
            "POST",
            f"/v1/checkout/sessions/{encoded}/expire",
            headers=self._headers(),
            idempotent=True,
            reference_id=session_id,
        )
        return _parse_optional_json_dict(response, reference_id=session_id)

    def search_checkout_sessions(
        self, client_reference: str
    ) -> list[WaveCheckoutSession]:
        """Search Wave checkout sessions by ``client_reference``."""
        encoded = _encode_wave_query_ref(client_reference)
        response = self._http.request(
            "GET",
            f"/v1/checkout/sessions/search?client_reference={encoded}",
            headers=self._headers(),
            reference_id=client_reference,
        )
        res = parse_json_dict(response, reference_id=client_reference)
        return _parse_wave_search_results(
            res, WaveCheckoutSession, reference_id=client_reference
        )

    def create_payout(
        self,
        amount: str,
        currency: str,
        mobile: str,
        *,
        client_reference: str | None = None,
        name: str | None = None,
        payment_reason: str | None = None,
        national_id: str | None = None,
        aggregated_merchant_id: str | None = None,
    ) -> WavePayoutResponse:
        """Send a Wave payout to a subscriber mobile number."""
        validated_amount = validate_amount(amount)
        validated_currency = validate_currency(currency)
        ref = client_reference or generate_reference_id()
        payload: dict[str, Any] = {
            "receive_amount": validated_amount,
            "currency": validated_currency,
            "mobile": f"+{normalise_msisdn(mobile)}",
            "client_reference": ref,
        }
        for key, val in (
            ("name", name),
            ("payment_reason", payment_reason),
            ("national_id", national_id),
            ("aggregated_merchant_id", aggregated_merchant_id),
        ):
            if val is not None:
                if not isinstance(val, str) or not val.strip():
                    raise ValueError(f"{key} must not be blank")
                payload[key] = val.strip()
        headers = self._headers(idempotency_key=ref)
        if self._config.signing_secret is not None:
            raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Wave-Signature"] = _sign_wave_request(
                raw_body, self._config.signing_secret
            )
            response = self._http.request(
                "POST",
                "/v1/payout",
                headers=headers,
                content=raw_body,
                idempotent=True,
                reference_id=ref,
            )
        else:
            response = self._http.request(
                "POST",
                "/v1/payout",
                headers=headers,
                json=payload,
                idempotent=True,
                reference_id=ref,
            )
        return parse_model(response, WavePayoutResponse, reference_id=ref)

    def get_payout(self, payout_id: str) -> WavePayoutResponse:
        """Retrieve a Wave payout status by ID."""
        encoded = encode_path_segment(payout_id, field_name="payout_id")
        response = self._http.request(
            "GET",
            f"/v1/payout/{encoded}",
            headers=self._headers(),
            reference_id=payout_id,
        )
        return parse_model(response, WavePayoutResponse, reference_id=payout_id)

    def reverse_payout(self, payout_id: str) -> dict[str, Any]:
        """Reverse a Wave payout (``POST /v1/payout/{id}/reverse``)."""
        encoded = encode_path_segment(payout_id, field_name="payout_id")
        headers = self._headers()
        if self._config.signing_secret is not None:
            headers["Wave-Signature"] = _sign_wave_request(
                b"", self._config.signing_secret
            )
        response = self._http.request(
            "POST",
            f"/v1/payout/{encoded}/reverse",
            headers=headers,
            content=b"",
            idempotent=False,
            reference_id=payout_id,
        )
        return _parse_optional_json_dict(response, reference_id=payout_id)

    def search_payouts(self, client_reference: str) -> list[WavePayoutResponse]:
        """Search Wave payouts by ``client_reference``."""
        encoded = _encode_wave_query_ref(client_reference)
        response = self._http.request(
            "GET",
            f"/v1/payouts/search?client_reference={encoded}",
            headers=self._headers(),
            reference_id=client_reference,
        )
        res = parse_json_dict(response, reference_id=client_reference)
        return _parse_wave_search_results(
            res, WavePayoutResponse, reference_id=client_reference
        )

    def get_balance(self) -> WaveBalanceResponse:
        """Retrieve the Wave merchant balance."""
        response = self._http.request(
            "GET",
            "/v1/balance",
            headers=self._headers(),
        )
        return parse_model(response, WaveBalanceResponse)

    def verify_webhook(
        self,
        payload: bytes,
        signature_header: str,
        *,
        tolerance_seconds: int = 300,
        max_future_skew_seconds: float = _WAVE_DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    ) -> None:
        """Verify a ``Wave-Signature`` header against raw request body bytes."""
        WebhookHandler.verify_timestamped_hmac_signature(
            payload,
            signature_header,
            self._config.webhook_secret or "",
            tolerance_seconds=tolerance_seconds,
            max_future_skew_seconds=max_future_skew_seconds,
            timestamp_separator="",
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
        self,
        config: WaveConfig,
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
            provider_name="Wave",
            allow_localhost=config.allow_localhost,
        )

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            validate_header_value(idempotency_key, field_name="client_reference")
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def create_checkout_session(
        self,
        amount: str,
        currency: str,
        *,
        client_reference: str | None = None,
        success_url: str | None = None,
        error_url: str | None = None,
        restrict_payer_mobile: str | None = None,
    ) -> WaveCheckoutSession:
        validated_amount = validate_amount(amount)
        validated_currency = validate_currency(currency)
        if success_url is not None:
            validate_callback_url(
                success_url, allow_localhost=self._config.allow_localhost
            )
        if error_url is not None:
            validate_callback_url(
                error_url, allow_localhost=self._config.allow_localhost
            )
        resolved_success = success_url or self._config.success_url
        resolved_error = error_url or self._config.error_url
        if not resolved_success or not resolved_error:
            raise ValueError(
                "success_url and error_url are required for Wave checkout sessions"
            )
        ref = client_reference or generate_reference_id()
        payload: dict[str, Any] = {
            "amount": validated_amount,
            "currency": validated_currency,
            "success_url": resolved_success,
            "error_url": resolved_error,
            "client_reference": ref,
        }
        if restrict_payer_mobile is not None:
            payload["restrict_payer_mobile"] = (
                f"+{normalise_msisdn(restrict_payer_mobile)}"
            )
        response = await self._http.request(
            "POST",
            "/v1/checkout/sessions",
            headers=self._headers(idempotency_key=ref),
            json=payload,
            idempotent=True,
            reference_id=ref,
        )
        return parse_model(response, WaveCheckoutSession, reference_id=ref)

    async def get_checkout_session(self, session_id: str) -> WaveCheckoutSession:
        encoded = encode_path_segment(session_id, field_name="session_id")
        response = await self._http.request(
            "GET",
            f"/v1/checkout/sessions/{encoded}",
            headers=self._headers(),
            reference_id=session_id,
        )
        return parse_model(response, WaveCheckoutSession, reference_id=session_id)

    async def refund_checkout_session(self, session_id: str) -> dict[str, Any]:
        """Refund a completed Wave checkout session asynchronously."""
        encoded = encode_path_segment(session_id, field_name="session_id")
        response = await self._http.request(
            "POST",
            f"/v1/checkout/sessions/{encoded}/refund",
            headers=self._headers(),
            idempotent=False,
            reference_id=session_id,
        )
        return _parse_optional_json_dict(response, reference_id=session_id)

    async def expire_checkout_session(self, session_id: str) -> dict[str, Any]:
        """Expire an open Wave checkout session asynchronously."""
        encoded = encode_path_segment(session_id, field_name="session_id")
        response = await self._http.request(
            "POST",
            f"/v1/checkout/sessions/{encoded}/expire",
            headers=self._headers(),
            idempotent=True,
            reference_id=session_id,
        )
        return _parse_optional_json_dict(response, reference_id=session_id)

    async def search_checkout_sessions(
        self, client_reference: str
    ) -> list[WaveCheckoutSession]:
        """Search Wave checkout sessions by ``client_reference`` asynchronously."""
        encoded = _encode_wave_query_ref(client_reference)
        response = await self._http.request(
            "GET",
            f"/v1/checkout/sessions/search?client_reference={encoded}",
            headers=self._headers(),
            reference_id=client_reference,
        )
        res = parse_json_dict(response, reference_id=client_reference)
        return _parse_wave_search_results(
            res, WaveCheckoutSession, reference_id=client_reference
        )

    async def create_payout(
        self,
        amount: str,
        currency: str,
        mobile: str,
        *,
        client_reference: str | None = None,
        name: str | None = None,
        payment_reason: str | None = None,
        national_id: str | None = None,
        aggregated_merchant_id: str | None = None,
    ) -> WavePayoutResponse:
        validated_amount = validate_amount(amount)
        validated_currency = validate_currency(currency)
        ref = client_reference or generate_reference_id()
        payload: dict[str, Any] = {
            "receive_amount": validated_amount,
            "currency": validated_currency,
            "mobile": f"+{normalise_msisdn(mobile)}",
            "client_reference": ref,
        }
        for key, val in (
            ("name", name),
            ("payment_reason", payment_reason),
            ("national_id", national_id),
            ("aggregated_merchant_id", aggregated_merchant_id),
        ):
            if val is not None:
                if not isinstance(val, str) or not val.strip():
                    raise ValueError(f"{key} must not be blank")
                payload[key] = val.strip()
        headers = self._headers(idempotency_key=ref)
        if self._config.signing_secret is not None:
            raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Wave-Signature"] = _sign_wave_request(
                raw_body, self._config.signing_secret
            )
            response = await self._http.request(
                "POST",
                "/v1/payout",
                headers=headers,
                content=raw_body,
                idempotent=True,
                reference_id=ref,
            )
        else:
            response = await self._http.request(
                "POST",
                "/v1/payout",
                headers=headers,
                json=payload,
                idempotent=True,
                reference_id=ref,
            )
        return parse_model(response, WavePayoutResponse, reference_id=ref)

    async def get_payout(self, payout_id: str) -> WavePayoutResponse:
        encoded = encode_path_segment(payout_id, field_name="payout_id")
        response = await self._http.request(
            "GET",
            f"/v1/payout/{encoded}",
            headers=self._headers(),
            reference_id=payout_id,
        )
        return parse_model(response, WavePayoutResponse, reference_id=payout_id)

    async def reverse_payout(self, payout_id: str) -> dict[str, Any]:
        """Reverse a Wave payout asynchronously."""
        encoded = encode_path_segment(payout_id, field_name="payout_id")
        headers = self._headers()
        if self._config.signing_secret is not None:
            headers["Wave-Signature"] = _sign_wave_request(
                b"", self._config.signing_secret
            )
        response = await self._http.request(
            "POST",
            f"/v1/payout/{encoded}/reverse",
            headers=headers,
            content=b"",
            idempotent=False,
            reference_id=payout_id,
        )
        return _parse_optional_json_dict(response, reference_id=payout_id)

    async def search_payouts(self, client_reference: str) -> list[WavePayoutResponse]:
        """Search Wave payouts by ``client_reference`` asynchronously."""
        encoded = _encode_wave_query_ref(client_reference)
        response = await self._http.request(
            "GET",
            f"/v1/payouts/search?client_reference={encoded}",
            headers=self._headers(),
            reference_id=client_reference,
        )
        res = parse_json_dict(response, reference_id=client_reference)
        return _parse_wave_search_results(
            res, WavePayoutResponse, reference_id=client_reference
        )

    async def get_balance(self) -> WaveBalanceResponse:
        response = await self._http.request(
            "GET",
            "/v1/balance",
            headers=self._headers(),
        )
        return parse_model(response, WaveBalanceResponse)

    def verify_webhook(
        self,
        payload: bytes,
        signature_header: str,
        *,
        tolerance_seconds: int = 300,
        max_future_skew_seconds: float = _WAVE_DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    ) -> None:
        """Verify a ``Wave-Signature`` header against raw request body bytes."""
        WebhookHandler.verify_timestamped_hmac_signature(
            payload,
            signature_header,
            self._config.webhook_secret or "",
            tolerance_seconds=tolerance_seconds,
            max_future_skew_seconds=max_future_skew_seconds,
            timestamp_separator="",
        )

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
            error_url=None,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=session.id,
            status=_map_wave_session_status(session),
            amount=session.amount,
            currency=session.currency,
            external_id=session.client_reference,
            provider_transaction_id=session.transaction_id,
            checkout_url=session.wave_launch_url,
            reason=_extract_wave_error(session.last_payment_error),
            raw=session.model_dump(mode="json"),
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        payout = self._client.create_payout(
            amount=request.amount,
            currency=request.currency,
            mobile=request.payee_msisdn,
            client_reference=request.reference_id or request.external_id or None,
            payment_reason=request.payer_message or None,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=payout.id,
            status=_map_wave_status(payout.status),
            amount=payout.receive_amount,
            currency=payout.currency,
            external_id=payout.client_reference,
            provider_transaction_id=payout.transaction_id,
            reason=_extract_wave_error(payout.payout_error),
            raw=payout.model_dump(mode="json"),
        )

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        if kind == "disbursement":
            payout = self._client.get_payout(reference_id)
            return PaymentResult(
                provider=self.name,
                reference_id=payout.id,
                status=_map_wave_status(payout.status),
                amount=payout.receive_amount,
                currency=payout.currency,
                external_id=payout.client_reference,
                provider_transaction_id=payout.transaction_id,
                reason=_extract_wave_error(payout.payout_error),
                raw=payout.model_dump(mode="json"),
            )
        session = self._client.get_checkout_session(reference_id)
        return PaymentResult(
            provider=self.name,
            reference_id=session.id,
            status=_map_wave_session_status(session),
            amount=session.amount,
            currency=session.currency,
            external_id=session.client_reference,
            provider_transaction_id=session.transaction_id,
            checkout_url=session.wave_launch_url,
            reason=_extract_wave_error(session.last_payment_error),
            raw=session.model_dump(mode="json"),
        )

    def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        del currency
        validate_operation_kind(kind)
        balance = self._client.get_balance()
        return BalanceResult(
            provider=self.name,
            available_balance=balance.amount,
            currency=balance.currency,
            raw=balance.model_dump(mode="json"),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


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
            error_url=None,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=session.id,
            status=_map_wave_session_status(session),
            amount=session.amount,
            currency=session.currency,
            external_id=session.client_reference,
            provider_transaction_id=session.transaction_id,
            checkout_url=session.wave_launch_url,
            reason=_extract_wave_error(session.last_payment_error),
            raw=session.model_dump(mode="json"),
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        payout = await self._client.create_payout(
            amount=request.amount,
            currency=request.currency,
            mobile=request.payee_msisdn,
            client_reference=request.reference_id or request.external_id or None,
            payment_reason=request.payer_message or None,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=payout.id,
            status=_map_wave_status(payout.status),
            amount=payout.receive_amount,
            currency=payout.currency,
            external_id=payout.client_reference,
            provider_transaction_id=payout.transaction_id,
            reason=_extract_wave_error(payout.payout_error),
            raw=payout.model_dump(mode="json"),
        )

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        if kind == "disbursement":
            payout = await self._client.get_payout(reference_id)
            return PaymentResult(
                provider=self.name,
                reference_id=payout.id,
                status=_map_wave_status(payout.status),
                amount=payout.receive_amount,
                currency=payout.currency,
                external_id=payout.client_reference,
                provider_transaction_id=payout.transaction_id,
                reason=_extract_wave_error(payout.payout_error),
                raw=payout.model_dump(mode="json"),
            )
        session = await self._client.get_checkout_session(reference_id)
        return PaymentResult(
            provider=self.name,
            reference_id=session.id,
            status=_map_wave_session_status(session),
            amount=session.amount,
            currency=session.currency,
            external_id=session.client_reference,
            provider_transaction_id=session.transaction_id,
            checkout_url=session.wave_launch_url,
            reason=_extract_wave_error(session.last_payment_error),
            raw=session.model_dump(mode="json"),
        )

    async def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        del currency
        validate_operation_kind(kind)
        balance = await self._client.get_balance()
        return BalanceResult(
            provider=self.name,
            available_balance=balance.amount,
            currency=balance.currency,
            raw=balance.model_dump(mode="json"),
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def close(self) -> None:
        await self.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
