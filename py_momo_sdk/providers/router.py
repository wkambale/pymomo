from __future__ import annotations

import inspect
import logging
import threading
from collections.abc import Collection, Mapping, Sequence
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

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
    validate_operation_kind,
)
from py_momo_sdk.utils import detect_carrier_from_msisdn, generate_reference_id

if TYPE_CHECKING:
    from typing_extensions import Self

logger = logging.getLogger("py_momo_sdk.providers")

_PROVIDER_METHODS = ("collect", "disburse", "get_status", "get_balance")


def _is_sync_provider(obj: object) -> bool:
    """Return True if ``obj`` implements synchronous ``PaymentProvider`` methods."""
    if not isinstance(obj, PaymentProvider):
        return False
    return all(
        callable(getattr(obj, m, None))
        and not inspect.iscoroutinefunction(getattr(obj, m, None))
        for m in _PROVIDER_METHODS
    )


def _is_async_provider(obj: object) -> bool:
    """Return True if ``obj`` implements asynchronous ``AsyncPaymentProvider`` coroutine methods."""
    if not isinstance(obj, AsyncPaymentProvider):
        return False
    return all(
        inspect.iscoroutinefunction(getattr(obj, m, None)) for m in _PROVIDER_METHODS
    )


def _is_valid_plugin_object(obj: object) -> bool:
    if _is_sync_provider(obj) or _is_async_provider(obj):
        return True
    # Reject hybrid objects that implement provider attributes with mixed sync/async methods
    if isinstance(obj, (PaymentProvider, AsyncPaymentProvider)):
        return False
    return callable(obj)


def discover_provider_plugins(
    *,
    allowed_plugins: Collection[str] | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Discover third-party provider adapters via ``py_momo_sdk.providers`` entry points.

    Args:
        allowed_plugins: Optional allowlist of entry-point names permitted to load.
            Unlisted entry points are skipped before ``load()`` executes.
        strict: When ``True`` (default), raise ``PyMomoSDKError`` if a plugin fails
            to load, collides on name, or does not conform to ``PaymentProvider`` /
            ``AsyncPaymentProvider`` / callable factory. When ``False``, log a
            warning and skip broken or duplicate plugins.

    Raises:
        TypeError: If ``allowed_plugins`` is a bare string or bytes.
        PyMomoSDKError: On duplicate entry-point collisions or (when ``strict=True``)
            load/validation errors.
    """
    allow_set: set[str] | None = None
    if allowed_plugins is not None:
        if isinstance(allowed_plugins, (str, bytes)):
            raise TypeError("allowed_plugins must be a collection of plugin names")
        allow_set = set(allowed_plugins)

    discovered: dict[str, Any] = {}
    seen_names: set[str] = set()
    for ep in entry_points(group="py_momo_sdk.providers"):
        if allow_set is not None and ep.name not in allow_set:
            continue
        if ep.name in seen_names:
            if strict:
                raise PyMomoSDKError(
                    f"Duplicate provider plugin entry point detected: {ep.name}"
                )
            logger.warning("Skipping duplicate provider plugin '%s'", ep.name)
            continue
        seen_names.add(ep.name)
        try:
            loaded = ep.load()
        except Exception as exc:
            if strict:
                raise PyMomoSDKError(
                    f"Failed to load provider plugin '{ep.name}'"
                ) from exc
            logger.warning(
                "Skipping broken provider plugin '%s'", ep.name, exc_info=True
            )
            continue

        if not _is_valid_plugin_object(loaded):
            if strict:
                raise PyMomoSDKError(
                    f"Plugin '{ep.name}' is not a valid PaymentProvider or factory"
                )
            logger.warning("Skipping invalid provider plugin '%s'", ep.name)
            continue

        discovered[ep.name] = loaded
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


def _ensure_status_supported(
    provider: PaymentProvider | AsyncPaymentProvider,
    *,
    provider_name: str,
    kind: str,
) -> None:
    validate_operation_kind(kind)
    caps = provider.capabilities
    if kind == "collection" and not caps.supports_collection:
        raise PyMomoSDKError(
            f"Provider '{provider_name}' does not support collection status queries"
        )
    if kind == "disbursement" and not caps.supports_disbursement:
        raise PyMomoSDKError(
            f"Provider '{provider_name}' does not support disbursement status queries"
        )


def _ensure_balance_supported(
    provider: PaymentProvider | AsyncPaymentProvider,
    *,
    provider_name: str,
    kind: str,
) -> None:
    validate_operation_kind(kind)
    if not provider.capabilities.supports_balance:
        raise PyMomoSDKError(
            f"Provider '{provider_name}' does not support balance queries"
        )


class PaymentRouter:
    """Thread-safe router for normalized payment operations across registered providers."""

    def __init__(
        self,
        providers: Sequence[PaymentProvider] = (),
        *,
        default_provider: str | None = None,
        custom_carrier_prefixes: Mapping[str, tuple[str, str]] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._providers: dict[str, PaymentProvider] = {}
        self._order: list[str] = []
        self._default_provider = default_provider
        self._custom_carrier_prefixes = (
            dict(custom_carrier_prefixes)
            if custom_carrier_prefixes is not None
            else None
        )
        for provider in providers:
            self.register(provider)
        if (
            self._default_provider is not None
            and self._default_provider not in self._providers
        ):
            raise PyMomoSDKError(
                f"Default provider is not registered: {self._default_provider}"
            )

    def register(self, provider: PaymentProvider) -> None:
        """Register a synchronous payment provider adapter."""
        if not _is_sync_provider(provider):
            raise TypeError(
                "PaymentRouter requires a synchronous PaymentProvider adapter"
            )
        with self._lock:
            is_new = provider.name not in self._providers
            self._providers[provider.name] = provider
            if is_new:
                self._order.append(provider.name)
            if self._default_provider is None:
                self._default_provider = provider.name

    def get(self, name: str) -> PaymentProvider:
        """Return a registered provider by name."""
        with self._lock:
            provider = self._providers.get(name)
        if provider is None:
            raise PyMomoSDKError(f"Provider is not registered: {name}")
        return provider

    def list_providers(self) -> list[str]:
        """Return registered provider identifiers in registration order."""
        with self._lock:
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
        with self._lock:
            providers_snapshot = dict(self._providers)
            order_snapshot = list(self._order)
            default_name = self._default_provider

        if provider is not None:
            explicit = providers_snapshot.get(provider)
            if explicit is None:
                raise PyMomoSDKError(f"Provider is not registered: {provider}")
            if not _supports_operation_and_currency(
                explicit, operation=operation, currency=currency
            ):
                raise PyMomoSDKError(
                    f"Provider '{provider}' does not support {operation} for currency '{currency}'"
                )
            candidates = [explicit]
        else:
            if default_name is not None and default_name not in providers_snapshot:
                raise PyMomoSDKError(
                    f"Default provider is not registered: {default_name}"
                )
            candidates = []
            inferred = (
                detect_carrier_from_msisdn(
                    msisdn, custom_prefixes=self._custom_carrier_prefixes
                )
                if msisdn
                else None
            )
            if inferred and inferred[1] in providers_snapshot:
                cand = providers_snapshot[inferred[1]]
                if _supports_operation_and_currency(
                    cand, operation=operation, currency=currency
                ):
                    candidates.append(cand)
            if not candidates and default_name and default_name in providers_snapshot:
                def_cand = providers_snapshot[default_name]
                if _supports_operation_and_currency(
                    def_cand, operation=operation, currency=currency
                ):
                    candidates.append(def_cand)

        if fallback:
            seen = {c.name for c in candidates}
            for name in order_snapshot:
                if name not in seen:
                    cand = providers_snapshot[name]
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
        reconcile transactions across both rails; when enabled, a deterministic
        ``reference_id`` is pre-generated before attempting the first rail so
        every attempted rail can be reconciled.
        """
        candidates = self._resolve_candidates(
            provider=provider,
            msisdn=request.payer_msisdn,
            operation="collection",
            currency=request.currency,
            fallback=fallback,
        )
        effective_request = request
        if (
            fallback
            and allow_ambiguous_write_fallback
            and len(candidates) > 1
            and effective_request.reference_id is None
        ):
            effective_request = effective_request.model_copy(
                update={"reference_id": generate_reference_id()}
            )
        failover_errors: tuple[type[PyMomoSDKError], ...] = (
            (AuthenticationError, MissingCredentialsError, PyMomoSDKServerError)
            if allow_ambiguous_write_fallback
            else (AuthenticationError, MissingCredentialsError)
        )
        last_exc: PyMomoSDKError | None = None
        attempted_refs: list[tuple[str, str | None]] = []
        for idx, candidate in enumerate(candidates):
            try:
                result = candidate.collect(effective_request)
                if attempted_refs:
                    result.raw.setdefault(
                        "prior_failed_attempts",
                        [{"provider": p, "reference_id": r} for p, r in attempted_refs],
                    )
                return result
            except failover_errors as exc:
                attempted_refs.append((candidate.name, effective_request.reference_id))
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
        effective_request = request
        if (
            fallback
            and allow_ambiguous_write_fallback
            and len(candidates) > 1
            and effective_request.reference_id is None
        ):
            effective_request = effective_request.model_copy(
                update={"reference_id": generate_reference_id()}
            )
        failover_errors: tuple[type[PyMomoSDKError], ...] = (
            (AuthenticationError, MissingCredentialsError, PyMomoSDKServerError)
            if allow_ambiguous_write_fallback
            else (AuthenticationError, MissingCredentialsError)
        )
        last_exc: PyMomoSDKError | None = None
        attempted_refs: list[tuple[str, str | None]] = []
        for idx, candidate in enumerate(candidates):
            try:
                result = candidate.disburse(effective_request)
                if attempted_refs:
                    result.raw.setdefault(
                        "prior_failed_attempts",
                        [{"provider": p, "reference_id": r} for p, r in attempted_refs],
                    )
                return result
            except failover_errors as exc:
                attempted_refs.append((candidate.name, effective_request.reference_id))
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
        target = self.get(provider)
        _ensure_status_supported(target, provider_name=provider, kind=kind)
        return target.get_status(reference_id, kind=kind)

    def get_balance(
        self,
        *,
        provider: str,
        kind: str = "collection",
        currency: str | None = None,
    ) -> BalanceResult:
        """Query account balance on a specific registered provider."""
        target = self.get(provider)
        _ensure_balance_supported(target, provider_name=provider, kind=kind)
        if currency is not None:
            return target.get_balance(kind=kind, currency=currency)
        return target.get_balance(kind=kind)

    def close(self) -> None:
        """Close all registered providers that expose a ``close()`` method."""
        with self._lock:
            providers_snapshot = list(self._providers.values())
        for prov in providers_snapshot:
            closer = getattr(prov, "close", None)
            if callable(closer):
                closer()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncPaymentRouter:
    """Asynchronous router for normalized payment operations across providers."""

    def __init__(
        self,
        providers: Sequence[AsyncPaymentProvider] = (),
        *,
        default_provider: str | None = None,
        custom_carrier_prefixes: Mapping[str, tuple[str, str]] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._providers: dict[str, AsyncPaymentProvider] = {}
        self._order: list[str] = []
        self._default_provider = default_provider
        self._custom_carrier_prefixes = (
            dict(custom_carrier_prefixes)
            if custom_carrier_prefixes is not None
            else None
        )
        for provider in providers:
            self.register(provider)
        if (
            self._default_provider is not None
            and self._default_provider not in self._providers
        ):
            raise PyMomoSDKError(
                f"Default provider is not registered: {self._default_provider}"
            )

    def register(self, provider: AsyncPaymentProvider) -> None:
        """Register an asynchronous payment provider adapter."""
        if not _is_async_provider(provider):
            raise TypeError(
                "AsyncPaymentRouter requires an asynchronous AsyncPaymentProvider adapter"
            )
        with self._lock:
            is_new = provider.name not in self._providers
            self._providers[provider.name] = provider
            if is_new:
                self._order.append(provider.name)
            if self._default_provider is None:
                self._default_provider = provider.name

    def get(self, name: str) -> AsyncPaymentProvider:
        """Return a registered async provider by name."""
        with self._lock:
            provider = self._providers.get(name)
        if provider is None:
            raise PyMomoSDKError(f"Provider is not registered: {name}")
        return provider

    def list_providers(self) -> list[str]:
        """Return registered provider identifiers in registration order."""
        with self._lock:
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
        with self._lock:
            providers_snapshot = dict(self._providers)
            order_snapshot = list(self._order)
            default_name = self._default_provider

        if provider is not None:
            explicit = providers_snapshot.get(provider)
            if explicit is None:
                raise PyMomoSDKError(f"Provider is not registered: {provider}")
            if not _supports_operation_and_currency(
                explicit, operation=operation, currency=currency
            ):
                raise PyMomoSDKError(
                    f"Provider '{provider}' does not support {operation} for currency '{currency}'"
                )
            candidates = [explicit]
        else:
            if default_name is not None and default_name not in providers_snapshot:
                raise PyMomoSDKError(
                    f"Default provider is not registered: {default_name}"
                )
            candidates = []
            inferred = (
                detect_carrier_from_msisdn(
                    msisdn, custom_prefixes=self._custom_carrier_prefixes
                )
                if msisdn
                else None
            )
            if inferred and inferred[1] in providers_snapshot:
                cand = providers_snapshot[inferred[1]]
                if _supports_operation_and_currency(
                    cand, operation=operation, currency=currency
                ):
                    candidates.append(cand)
            if not candidates and default_name and default_name in providers_snapshot:
                def_cand = providers_snapshot[default_name]
                if _supports_operation_and_currency(
                    def_cand, operation=operation, currency=currency
                ):
                    candidates.append(def_cand)

        if fallback:
            seen = {c.name for c in candidates}
            for name in order_snapshot:
                if name not in seen:
                    cand = providers_snapshot[name]
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
        effective_request = request
        if (
            fallback
            and allow_ambiguous_write_fallback
            and len(candidates) > 1
            and effective_request.reference_id is None
        ):
            effective_request = effective_request.model_copy(
                update={"reference_id": generate_reference_id()}
            )
        failover_errors: tuple[type[PyMomoSDKError], ...] = (
            (AuthenticationError, MissingCredentialsError, PyMomoSDKServerError)
            if allow_ambiguous_write_fallback
            else (AuthenticationError, MissingCredentialsError)
        )
        last_exc: PyMomoSDKError | None = None
        attempted_refs: list[tuple[str, str | None]] = []
        for idx, candidate in enumerate(candidates):
            try:
                result = await candidate.collect(effective_request)
                if attempted_refs:
                    result.raw.setdefault(
                        "prior_failed_attempts",
                        [{"provider": p, "reference_id": r} for p, r in attempted_refs],
                    )
                return result
            except failover_errors as exc:
                attempted_refs.append((candidate.name, effective_request.reference_id))
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
        effective_request = request
        if (
            fallback
            and allow_ambiguous_write_fallback
            and len(candidates) > 1
            and effective_request.reference_id is None
        ):
            effective_request = effective_request.model_copy(
                update={"reference_id": generate_reference_id()}
            )
        failover_errors: tuple[type[PyMomoSDKError], ...] = (
            (AuthenticationError, MissingCredentialsError, PyMomoSDKServerError)
            if allow_ambiguous_write_fallback
            else (AuthenticationError, MissingCredentialsError)
        )
        last_exc: PyMomoSDKError | None = None
        attempted_refs: list[tuple[str, str | None]] = []
        for idx, candidate in enumerate(candidates):
            try:
                result = await candidate.disburse(effective_request)
                if attempted_refs:
                    result.raw.setdefault(
                        "prior_failed_attempts",
                        [{"provider": p, "reference_id": r} for p, r in attempted_refs],
                    )
                return result
            except failover_errors as exc:
                attempted_refs.append((candidate.name, effective_request.reference_id))
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
        target = self.get(provider)
        _ensure_status_supported(target, provider_name=provider, kind=kind)
        return await target.get_status(reference_id, kind=kind)

    async def get_balance(
        self,
        *,
        provider: str,
        kind: str = "collection",
        currency: str | None = None,
    ) -> BalanceResult:
        target = self.get(provider)
        _ensure_balance_supported(target, provider_name=provider, kind=kind)
        if currency is not None:
            return await target.get_balance(kind=kind, currency=currency)
        return await target.get_balance(kind=kind)

    async def aclose(self) -> None:
        """Asynchronously close all registered providers that expose ``aclose()`` or ``close()``."""
        with self._lock:
            providers_snapshot = list(self._providers.values())
        for prov in providers_snapshot:
            acloser = getattr(prov, "aclose", None)
            if callable(acloser):
                res = acloser()
                if inspect.isawaitable(res):
                    await res
                continue
            closer = getattr(prov, "close", None)
            if callable(closer):
                res = closer()
                if inspect.isawaitable(res):
                    await res

    async def close(self) -> None:
        """Alias for ``aclose()``."""
        await self.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
