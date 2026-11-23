from __future__ import annotations

from typing import Protocol, runtime_checkable

from py_momo_sdk.providers.models import (
    BalanceResult,
    DisbursementRequest,
    PaymentRequest,
    PaymentResult,
    ProviderCapabilities,
)


@runtime_checkable
class PaymentProvider(Protocol):
    """Synchronous unified interface for mobile money and payment gateway adapters."""

    @property
    def name(self) -> str:
        """Return the canonical provider identifier (for example ``'mtn_momo'``)."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return declarative capabilities for this provider."""

    def collect(self, request: PaymentRequest) -> PaymentResult:
        """Initiate a collection request."""

    def disburse(self, request: DisbursementRequest) -> PaymentResult:
        """Initiate a disbursement payout."""

    def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        """Query transaction status for a collection or disbursement."""

    def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        """Query the merchant account balance."""


@runtime_checkable
class AsyncPaymentProvider(Protocol):
    """Asynchronous unified interface for mobile money and payment gateway adapters."""

    @property
    def name(self) -> str:
        """Return the canonical provider identifier."""

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return declarative capabilities for this provider."""

    async def collect(self, request: PaymentRequest) -> PaymentResult:
        """Initiate a collection request asynchronously."""

    async def disburse(self, request: DisbursementRequest) -> PaymentResult:
        """Initiate a disbursement payout asynchronously."""

    async def get_status(
        self, reference_id: str, *, kind: str = "collection"
    ) -> PaymentResult:
        """Query transaction status asynchronously."""

    async def get_balance(
        self, *, kind: str = "collection", currency: str | None = None
    ) -> BalanceResult:
        """Query the merchant account balance asynchronously."""
