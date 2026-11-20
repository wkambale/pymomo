from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float  # Monotonic timestamp

    def __repr__(self) -> str:
        return f"_CachedToken(access_token=<redacted>, expires_at={self.expires_at!r})"

    def __str__(self) -> str:
        return self.__repr__()


class TokenCache:
    """Thread-safe in-memory OAuth token cache."""

    def __init__(self) -> None:
        self._cache: dict[str, _CachedToken] = {}
        self._lock = threading.Lock()

    def get(self, product: str) -> str | None:
        """Return a valid cached token or None if absent or expired."""
        with self._lock:
            entry = self._cache.get(product)
            if entry is None:
                return None
            if time.monotonic() >= entry.expires_at:
                del self._cache[product]
                return None
            return entry.access_token

    def set(self, product: str, access_token: str, expires_in: int) -> None:
        """Cache a token with a 30-second safety margin before expiry."""
        expires_at = time.monotonic() + expires_in - 30
        with self._lock:
            self._cache[product] = _CachedToken(
                access_token=access_token,
                expires_at=expires_at,
            )

    def invalidate(self, product: str, *, expected_token: str | None = None) -> None:
        """Remove a cached token, forcing the next call to re-authenticate.

        When ``expected_token`` is supplied, the entry is only removed if the
        currently cached token matches ``expected_token``, preventing a stale
        401 response from evicting a concurrently refreshed token.
        """
        with self._lock:
            if expected_token is not None:
                entry = self._cache.get(product)
                if entry is None or entry.access_token != expected_token:
                    return
            self._cache.pop(product, None)

    def __repr__(self) -> str:
        with self._lock:
            products = sorted(self._cache.keys())
        return f"TokenCache(products={products!r})"

    def __str__(self) -> str:
        return self.__repr__()
