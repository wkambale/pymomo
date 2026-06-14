from __future__ import annotations

from pymomo.auth import TokenCache


def test_token_cache_get_set_invalidate() -> None:
    """Verify standard set, get, and invalidate behaviors on TokenCache."""
    cache = TokenCache()

    # Get non-existent token
    assert cache.get("collection") is None

    # Set token with long expiry (e.g. 1 hour)
    cache.set("collection", "token-1", 3600)
    assert cache.get("collection") == "token-1"

    # Invalidate token
    cache.invalidate("collection")
    assert cache.get("collection") is None


def test_token_cache_safety_margin_expiry() -> None:
    """Verify that token expires prematurely based on the 30 seconds safety margin."""
    cache = TokenCache()

    # If token expires in 31 seconds, the cache safety margin of 30 seconds leaves 1 second of validity
    cache.set("collection", "token-2", 31)
    assert cache.get("collection") == "token-2"

    # If token expires in 29 seconds, it is immediately treated as expired
    cache.set("collection", "token-3", 29)
    assert cache.get("collection") is None
