from __future__ import annotations

from collections.abc import Sequence
from importlib.metadata import entry_points
from typing import Any

from py_momo_sdk.exceptions import (
    AuthenticationError,
    MissingCredentialsError,
    PyMomoSDKError,
    PyMomoSDKServerError,
)
from py_momo_sdk.providers.base import AsyncPaymentProvider, PaymentProvider
from py_momo_sdk.providers.models import (
    BalanceResult,
    DisbursementRequest,
    PaymentRequest,
    PaymentResult,
)
from py_momo_sdk.utils import detect_carrier_from_msisdn


def discover_provider_plugins() -> dict[str, Any]:
    """Discover third-party provider adapters via ``py_momo_sdk.providers`` entry points."""
    discovered: dict[str, Any] = {}
    for ep in entry_points(group="py_momo_sdk.providers"):
        discovered[ep.name] = ep.load()
    return discovered


def _supports_operation_and_currency(
    provider: PaymentProvider | AsyncPaymentProvider,
    *,
    operation: str,
    currency: str,
) -> bool:
    caps = provider.capabilities
    if operation == "collection" and not caps.supports_collection:
        return False
    if operation == "disbursement" and not caps.supports_disbursement:
        return False
    norm_currency = currency.upper()
    return not caps.currencies or norm_currency in caps.currencies


class PaymentRouter:
    """Route normalized payment operations across registered providers."""

    def __init__(
        self,
        providers: Sequence[PaymentProvider] = (),
        *,
        default_provider: str | None = None,
    ) -> None:
        self._providers: dict[str, PaymentProvider] = {}
        self._order: list[str] = []
        self._default_provider = default_provider
        for provider in providers:
            self.register(provider)
        if (
            providers
            and self._default_provider is not None
            and self._default_provider not in self._providers
        ):
            raise PyMomoSDKError(
                f"Default provider is not registered: {self._default_provider}"
            )

    def register(self, provider: PaymentProvider) -> None:
        """Register a synchronous payment provider adapter."""
        if provider.name not in self._providers:
            self._order.append(provider.name)
        self._providers[provider.name] = provider
        if self._default_provider is None:
            self._default_provider = provider.name

    def get(self, name: str) -> PaymentProvider:
        """Return a registered provider by name."""
        provider = self._providers.get(name)
        if provider is None:
            raise PyMomoSDKError(f"Provider is not registered: {name}")
        return provider

    def list_providers(self) -> list[str]:
        """Return registered provider identifiers in registration order."""
        return list(self._order)

    def _resolve_candidates(
        self,
        *,
        provider: str | None,
        msisdn: str | None,
        operation: str,
        currency: str,
        fallback: bool,
    ) -> list[PaymentProvider]:
        if provider is not None:
            explicit = self.get(provider)
            if not _supports_operation_and_currency(
                explicit, operation=operation, currency=currency
            ):
                raise PyMomoSDKError(
                    f"Provider '{provider}' does not support {operation} for currency '{currency}'"
                )
            candidates = [explicit]
        else:
            if (
                self._default_provider is not None
                and self._default_provider not in self._providers
            ):
                raise PyMomoSDKError(
                    f"Default provider is not registered: {self._default_provider}"
                )
            candidates = []
            inferred = detect_carrier_from_msisdn(msisdn) if msisdn else None
            if inferred and inferred[1] in self._providers:
                cand = self._providers[inferred[1]]
                if _supports_operation_and_currency(
                    cand, operation=operation, currency=currency
                ):
                    candidates.append(cand)
            if (
                not candidates
                and self._default_provider
                and self._default_provider in self._providers
            ):
                def_cand = self._providers[self._default_provider]
                if _supports_operation_and_currency(
                    def_cand, operation=operation, currency=currency
                ):
                    candidates.append(def_cand)

        if fallback:
            seen = {c.name for c in candidates}
            for name in self._order:
                if name not in seen:
                    cand = self._providers[name]
                    if _supports_operation_and_currency(
                        cand, operation=operation, currency=currency
                    ):
                        candidates.append(cand)
                        seen.add(name)

        if not candidates:
            raise PyMomoSDKError("No matching payment provider is registered")
        return candidates

    def collect(
        self,
        request: PaymentRequest,
        *,
        provider: str | None = None,
        fallback: bool = False,
        allow_ambiguous_write_fallback: bool = False,
    ) -> PaymentResult:
        """Route a collection request to an explicit, carrier-inferred, or fallback rail.

        By default, ``fallback=True`` only fails over on unambiguous pre-flight
        authentication/credential errors (``AuthenticationError``,
        ``MissingCredentialsError``) to prevent double-charging on ambiguous 5xx
        responses. Pass ``allow_ambiguous_write_fallback=True`` only if you
        reconcile transactions across both rails.
        """
        candidates = self._resolve_candidates(
            provider=provider,
            msisdn=request.payer_msisdn,
            operation="collection",
            currency=request.currency,
            fallback=fallback,
        )
        failover_errors: tuple[type[PyMomoSDKError], ...] = (
            (AuthenticationError, MissingCredentialsError, PyMomoSDKServerError)
            if allow_ambiguous_write_fallback
            else (AuthenticationError, MissingCredentialsError)
        )
        last_exc: PyMomoSDKError | None = None
        for idx, candidate in enumerate(candidates):
            try:
                return candidate.collect(request)
            except failover_errors as exc:
                last_exc = exc
                if idx + 1 >= len(candidates):
                    raise
        raise last_exc or PyMomoSDKError("All payment providers failed")

    def disburse(
        self,
        request: DisbursementRequest,
        *,
        provider: str | None = None,
        fallback: bool = False,
        allow_ambiguous_write_fallback: bool = False,
    ) -> PaymentResult:
        """Route a disbursement request to an explicit, carrier-inferred, or fallback rail."""
        candidates = self._resolve_candidates(
            provider=provider,
            msisdn=request.payee_msisdn,
            operation="disbursement",
            currency=request.currency,
            fallback=fallback,
        )
        failover_errors: tuple[type[PyMomoSDKError], ...] = (
            (AuthenticationError, MissingCredentialsError, PyMomoSDKServerError)
            if allow_ambiguous_write_fallback
            else (AuthenticationError, MissingCredentialsError)
        )
        last_exc: PyMomoSDKError | None = None
        for idx, candidate in enumerate(candidates):
            try:
                return candidate.disburse(request)
            except failover_errors as exc:
                last_exc = exc
                if idx + 1 >= len(candidates):
                    raise
        raise last_exc or PyMomoSDKError("All payment providers failed")

    def get_status(
        self,
        reference_id: str,
        *,
        provider: str,
        kind: str = "collection",
    ) -> PaymentResult:
        """Query transaction status on a specific registered provider."""
        return self.get(provider).get_status(reference_id, kind=kind)

    def get_balance(
        self,
        *,
        provider: str,
        kind: str = "collection",
    ) -> BalanceResult:
        """Query account balance on a specific registered provider."""
        return self.get(provider).get_balance(kind=kind)


class AsyncPaymentRouter:
    """Asynchronous router for normalized payment operations across providers."""

    def __init__(
        self,
        providers: Sequence[AsyncPaymentProvider] = (),
        *,
        default_provider: str | None = None,
    ) -> None:
        self._providers: dict[str, AsyncPaymentProvider] = {}
        self._order: list[str] = []
        self._default_provider = default_provider
        for provider in providers:
            self.register(provider)
        if (
            providers
            and self._default_provider is not None
            and self._default_provider not in self._providers
        ):
            raise PyMomoSDKError(
                f"Default provider is not registered: {self._default_provider}"
            )

    def register(self, provider: AsyncPaymentProvider) -> None:
        """Register an asynchronous payment provider adapter."""
        if provider.name not in self._providers:
            self._order.append(provider.name)
        self._providers[provider.name] = provider
        if self._default_provider is None:
            self._default_provider = provider.name

    def get(self, name: str) -> AsyncPaymentProvider:
        """Return a registered async provider by name."""
        provider = self._providers.get(name)
        if provider is None:
            raise PyMomoSDKError(f"Provider is not registered: {name}")
        return provider

    def list_providers(self) -> list[str]:
        """Return registered provider identifiers in registration order."""
        return list(self._order)

    def _resolve_candidates(
        self,
        *,
        provider: str | None,
        msisdn: str | None,
        operation: str,
        currency: str,
        fallback: bool,
    ) -> list[AsyncPaymentProvider]:
        if provider is not None:
            explicit = self.get(provider)
            if not _supports_operation_and_currency(
                explicit, operation=operation, currency=currency
            ):
                raise PyMomoSDKError(
                    f"Provider '{provider}' does not support {operation} for currency '{currency}'"
                )
            candidates = [explicit]
        else:
            if (
                self._default_provider is not None
                and self._default_provider not in self._providers
            ):
                raise PyMomoSDKError(
                    f"Default provider is not registered: {self._default_provider}"
                )
            candidates = []
            inferred = detect_carrier_from_msisdn(msisdn) if msisdn else None
            if inferred and inferred[1] in self._providers:
                cand = self._providers[inferred[1]]
                if _supports_operation_and_currency(
                    cand, operation=operation, currency=currency
                ):
                    candidates.append(cand)
            if (
                not candidates
                and self._default_provider
                and self._default_provider in self._providers
            ):
                def_cand = self._providers[self._default_provider]
                if _supports_operation_and_currency(
                    def_cand, operation=operation, currency=currency
                ):
                    candidates.append(def_cand)

        if fallback:
            seen = {c.name for c in candidates}
            for name in self._order:
                if name not in seen:
                    cand = self._providers[name]
                    if _supports_operation_and_currency(
                        cand, operation=operation, currency=currency
                    ):
                        candidates.append(cand)
                        seen.add(name)

        if not candidates:
            raise PyMomoSDKError("No matching payment provider is registered")
        return candidates

    async def collect(
        self,
        request: PaymentRequest,
        *,
        provider: str | None = None,
        fallback: bool = False,
        allow_ambiguous_write_fallback: bool = False,
    ) -> PaymentResult:
        candidates = self._resolve_candidates(
            provider=provider,
            msisdn=request.payer_msisdn,
            operation="collection",
            currency=request.currency,
            fallback=fallback,
        )
        failover_errors: tuple[type[PyMomoSDKError], ...] = (
            (AuthenticationError, MissingCredentialsError, PyMomoSDKServerError)
            if allow_ambiguous_write_fallback
            else (AuthenticationError, MissingCredentialsError)
        )
        last_exc: PyMomoSDKError | None = None
        for idx, candidate in enumerate(candidates):
            try:
                return await candidate.collect(request)
            except failover_errors as exc:
                last_exc = exc
                if idx + 1 >= len(candidates):
                    raise
        raise last_exc or PyMomoSDKError("All payment providers failed")

    async def disburse(
        self,
        request: DisbursementRequest,
        *,
        provider: str | None = None,
        fallback: bool = False,
        allow_ambiguous_write_fallback: bool = False,
    ) -> PaymentResult:
        candidates = self._resolve_candidates(
            provider=provider,
            msisdn=request.payee_msisdn,
            operation="disbursement",
            currency=request.currency,
            fallback=fallback,
        )
        failover_errors: tuple[type[PyMomoSDKError], ...] = (
            (AuthenticationError, MissingCredentialsError, PyMomoSDKServerError)
            if allow_ambiguous_write_fallback
            else (AuthenticationError, MissingCredentialsError)
        )
        last_exc: PyMomoSDKError | None = None
        for idx, candidate in enumerate(candidates):
            try:
                return await candidate.disburse(request)
            except failover_errors as exc:
                last_exc = exc
                if idx + 1 >= len(candidates):
                    raise
        raise last_exc or PyMomoSDKError("All payment providers failed")

    async def get_status(
        self,
        reference_id: str,
        *,
        provider: str,
        kind: str = "collection",
    ) -> PaymentResult:
        return await self.get(provider).get_status(reference_id, kind=kind)

    async def get_balance(
        self,
        *,
        provider: str,
        kind: str = "collection",
    ) -> BalanceResult:
        return await self.get(provider).get_balance(kind=kind)
