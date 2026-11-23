from __future__ import annotations

from typing import TYPE_CHECKING

from py_momo_sdk._async.airtel.client import AsyncAirtelClient
from py_momo_sdk.airtel.client import AirtelClient
from py_momo_sdk.airtel.models import AirtelTransactionResponse
from py_momo_sdk.providers.models import (
    BalanceResult,
    DisbursementRequest,
    NormalizedStatus,
    PaymentRequest,
    PaymentResult,
    ProviderCapabilities,
    validate_operation_kind,
)

if TYPE_CHECKING:
    from typing_extensions import Self

_AIRTEL_CAPABILITIES = ProviderCapabilities(
    provider_id="airtel_money",
    supports_collection=True,
    supports_disbursement=True,
    supports_balance=True,
    supports_webhook_hmac=False,
    currencies=("UGX", "KES", "TZS", "RWF", "ZMW", "MWK", "NGN", "XAF", "XOF"),
)


def _check_airtel_currency(request_currency: str, configured_currency: str) -> str:
    expected = configured_currency.upper()
    actual = request_currency.upper()
    if actual != expected:
        raise ValueError(
            f"Request currency {actual!r} does not match configured Airtel currency {expected!r}"
        )
    return expected


def _map_airtel_result(
    reference_id: str, result: AirtelTransactionResponse
) -> PaymentResult:
    if result.is_successful():
        status = NormalizedStatus.SUCCEEDED
    elif result.is_failed():
        status = NormalizedStatus.FAILED
    else:
        status = NormalizedStatus.PENDING

    tx = result.data.transaction
    return PaymentResult(
        provider="airtel_money",
        reference_id=reference_id,
        status=status,
        amount=tx.amount,
        currency=tx.currency,
        provider_transaction_id=tx.airtel_money_id or tx.id,
        external_id=tx.reference,
        reason=tx.message or result.status.message,
        raw=result.model_dump(mode="json"),
    )


class AirtelMoneyProvider:
    """Synchronous unified provider adapter for Airtel Money."""

    def __init__(self, client: AirtelClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "airtel_money"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _AIRTEL_CAPABILITIES

    def collect(self, request: PaymentRequest) -> PaymentResult:
        currency = _check_airtel_currency(
            request.currency, self._client._config.currency
        )
        ref = self._client.collection.request_to_pay(
            amount=request.amount,
            payer_msisdn=request.payer_msisdn,
            reference_id=request.reference_id,
            external_id=request.external_id or None,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=currency,
            external_id=request.external_id or None,
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        currency = _check_airtel_currency(
            request.currency, self._client._config.currency
        )
        ref = self._client.disbursement.transfer(
            amount=request.amount,
            payee_msisdn=request.payee_msisdn,
            reference_id=request.reference_id,
            external_id=request.external_id or None,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=currency,
            external_id=request.external_id or None,
        )

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        if kind == "disbursement":
            result = self._client.disbursement.get_transfer_status(reference_id)
        else:
            result = self._client.collection.get_payment_status(reference_id)
        return _map_airtel_result(reference_id, result)

    def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        validate_operation_kind(kind)
        if currency is not None:
            _check_airtel_currency(currency, self._client._config.currency)
        balance = self._client.disbursement.get_balance()
        wallet = balance.data.wallet
        return BalanceResult(
            provider=self.name,
            available_balance=wallet.balance,
            currency=wallet.currency,
            raw=balance.model_dump(mode="json"),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncAirtelMoneyProvider:
    """Asynchronous unified provider adapter for Airtel Money."""

    def __init__(self, client: AsyncAirtelClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "airtel_money"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _AIRTEL_CAPABILITIES

    async def collect(self, request: PaymentRequest) -> PaymentResult:
        currency = _check_airtel_currency(
            request.currency, self._client._config.currency
        )
        ref = await self._client.collection.request_to_pay(
            amount=request.amount,
            payer_msisdn=request.payer_msisdn,
            reference_id=request.reference_id,
            external_id=request.external_id or None,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=currency,
            external_id=request.external_id or None,
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        currency = _check_airtel_currency(
            request.currency, self._client._config.currency
        )
        ref = await self._client.disbursement.transfer(
            amount=request.amount,
            payee_msisdn=request.payee_msisdn,
            reference_id=request.reference_id,
            external_id=request.external_id or None,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=currency,
            external_id=request.external_id or None,
        )

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        if kind == "disbursement":
            result = await self._client.disbursement.get_transfer_status(reference_id)
        else:
            result = await self._client.collection.get_payment_status(reference_id)
        return _map_airtel_result(reference_id, result)

    async def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        validate_operation_kind(kind)
        if currency is not None:
            _check_airtel_currency(currency, self._client._config.currency)
        balance = await self._client.disbursement.get_balance()
        wallet = balance.data.wallet
        return BalanceResult(
            provider=self.name,
            available_balance=wallet.balance,
            currency=wallet.currency,
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
