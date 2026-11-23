from __future__ import annotations

import threading
import time
from dataclasses import dataclass

_MAX_TOKEN_TTL_SECONDS = (
    365 * 24 * 60 * 60
)  # 1 year upper bound prevents float overflow


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float  # Monotonic timestamp

    def __repr__(self) -> str:
        return f"_CachedToken(access_token=<redacted>, expires_at={self.expires_at!r})"

    def __str__(self) -> str:
        return self.__repr__()


class TokenCache:
    """Thread-safe in-memory OAuth token cache with optional namespace isolation."""

    def __init__(self) -> None:
        self._cache: dict[str, _CachedToken] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _make_key(product: str, namespace: str) -> str:
        return f"{namespace}:{product}" if namespace else product

    def get(self, product: str, *, namespace: str = "") -> str | None:
        """Return a valid cached token or None if absent or expired."""
        key = self._make_key(product, namespace)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.monotonic() >= entry.expires_at:
                del self._cache[key]
                return None
            return entry.access_token

    def set(
        self,
        product: str,
        access_token: str,
        expires_in: int,
        *,
        namespace: str = "",
    ) -> None:
        """Cache a token with a safety margin before expiry (up to 30 seconds).

        For short-lived tokens (``expires_in <= 150``), scales the safety margin
        to 20% of ``expires_in`` so tokens with ``expires_in <= 30`` remain usable
        instead of expiring immediately.
        """
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("access_token must be a non-empty string")
        if (
            type(expires_in) is bool
            or not isinstance(expires_in, int)
            or expires_in <= 0
        ):
            raise ValueError("expires_in must be a positive integer")
        bounded_ttl = min(expires_in, _MAX_TOKEN_TTL_SECONDS)
        margin = min(30.0, bounded_ttl * 0.2)
        expires_at = time.monotonic() + bounded_ttl - margin
        key = self._make_key(product, namespace)
        with self._lock:
            self._cache[key] = _CachedToken(
                access_token=access_token,
                expires_at=expires_at,
            )

    def invalidate(
        self,
        product: str,
        *,
        expected_token: str | None = None,
        namespace: str = "",
    ) -> None:
        """Remove a cached token, forcing the next call to re-authenticate.

        When ``expected_token`` is supplied, the entry is only removed if the
        currently cached token matches ``expected_token``, preventing a stale
        401 response from evicting a concurrently refreshed token.
        """
        key = self._make_key(product, namespace)
        with self._lock:
            if expected_token is not None:
                entry = self._cache.get(key)
                if entry is None or entry.access_token != expected_token:
                    return
            self._cache.pop(key, None)

    def __repr__(self) -> str:
        with self._lock:
            products = sorted(self._cache.keys())
        return f"TokenCache(products={products!r})"

    def __str__(self) -> str:
        return self.__repr__()
