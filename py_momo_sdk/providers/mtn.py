from __future__ import annotations

from py_momo_sdk._async.client import AsyncPyMomoSDK
from py_momo_sdk.client import PyMomoSDK
from py_momo_sdk.models import TransactionResult, TransactionStatus
from py_momo_sdk.providers.models import (
    BalanceResult,
    DisbursementRequest,
    NormalizedStatus,
    PaymentRequest,
    PaymentResult,
    ProviderCapabilities,
    validate_operation_kind,
)
from py_momo_sdk.utils import generate_reference_id

_MTN_STATUS_MAP = {
    TransactionStatus.pending: NormalizedStatus.PENDING,
    TransactionStatus.successful: NormalizedStatus.SUCCEEDED,
    TransactionStatus.failed: NormalizedStatus.FAILED,
}

_MTN_CAPABILITIES = ProviderCapabilities(
    provider_id="mtn_momo",
    supports_collection=True,
    supports_disbursement=True,
    supports_balance=True,
    supports_webhook_hmac=False,
    currencies=("UGX", "GHS", "ZMW", "XAF", "XOF", "EUR", "ZAR", "SZL", "LRD", "GNF"),
)


def _map_mtn_result(reference_id: str, result: TransactionResult) -> PaymentResult:
    return PaymentResult(
        provider="mtn_momo",
        reference_id=reference_id,
        status=_MTN_STATUS_MAP[result.status],
        amount=result.amount,
        currency=result.currency,
        provider_transaction_id=result.financial_transaction_id,
        external_id=result.external_id,
        reason=result.reason,
        raw=result.model_dump(mode="json"),
    )


class MtnMomoProvider:
    """Synchronous unified provider adapter for MTN MoMo."""

    def __init__(self, client: PyMomoSDK) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "mtn_momo"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _MTN_CAPABILITIES

    def collect(self, request: PaymentRequest) -> PaymentResult:
        planned_ref = request.reference_id or generate_reference_id()
        ext_id = request.external_id or planned_ref
        ref = self._client.collection.request_to_pay(
            amount=request.amount,
            currency=request.currency,
            payer_msisdn=request.payer_msisdn,
            external_id=ext_id,
            payer_message=request.payer_message,
            payee_note=request.payee_note,
            reference_id=planned_ref,
            callback_url=request.callback_url,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=ext_id,
        )

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        planned_ref = request.reference_id or generate_reference_id()
        ext_id = request.external_id or planned_ref
        ref = self._client.disbursement.transfer(
            amount=request.amount,
            currency=request.currency,
            payee_msisdn=request.payee_msisdn,
            external_id=ext_id,
            payer_message=request.payer_message,
            payee_note=request.payee_note,
            reference_id=planned_ref,
            callback_url=request.callback_url,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=ext_id,
        )

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        if kind == "disbursement":
            result = self._client.disbursement.get_transfer_status(reference_id)
        else:
            result = self._client.collection.get_payment_status(reference_id)
        return _map_mtn_result(reference_id, result)

    def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        validate_operation_kind(kind)
        balance = (
            self._client.disbursement.get_balance()
            if kind == "disbursement"
            else self._client.collection.get_balance()
        )
        return BalanceResult(
            provider=self.name,
            available_balance=balance.available_balance,
            currency=balance.currency,
            raw=balance.model_dump(mode="json"),
        )


class AsyncMtnMomoProvider:
    """Asynchronous unified provider adapter for MTN MoMo."""

    def __init__(self, client: AsyncPyMomoSDK) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "mtn_momo"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return _MTN_CAPABILITIES

    async def collect(self, request: PaymentRequest) -> PaymentResult:
        planned_ref = request.reference_id or generate_reference_id()
        ext_id = request.external_id or planned_ref
        ref = await self._client.collection.request_to_pay(
            amount=request.amount,
            currency=request.currency,
            payer_msisdn=request.payer_msisdn,
            external_id=ext_id,
            payer_message=request.payer_message,
            payee_note=request.payee_note,
            reference_id=planned_ref,
            callback_url=request.callback_url,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=ext_id,
        )

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        planned_ref = request.reference_id or generate_reference_id()
        ext_id = request.external_id or planned_ref
        ref = await self._client.disbursement.transfer(
            amount=request.amount,
            currency=request.currency,
            payee_msisdn=request.payee_msisdn,
            external_id=ext_id,
            payer_message=request.payer_message,
            payee_note=request.payee_note,
            reference_id=planned_ref,
            callback_url=request.callback_url,
        )
        return PaymentResult(
            provider=self.name,
            reference_id=ref,
            status=NormalizedStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            external_id=ext_id,
        )

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        validate_operation_kind(kind)
        if kind == "disbursement":
            result = await self._client.disbursement.get_transfer_status(reference_id)
        else:
            result = await self._client.collection.get_payment_status(reference_id)
        return _map_mtn_result(reference_id, result)

    async def get_balance(self, *, kind: str = "collection") -> BalanceResult:
        validate_operation_kind(kind)
        balance = (
            await self._client.disbursement.get_balance()
            if kind == "disbursement"
            else await self._client.collection.get_balance()
        )
        return BalanceResult(
            provider=self.name,
            available_balance=balance.available_balance,
            currency=balance.currency,
            raw=balance.model_dump(mode="json"),
        )
