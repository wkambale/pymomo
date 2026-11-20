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


def test_token_cache_and_airtel_auth_redaction() -> None:
    """Verify token caches and AirtelAuth redact secrets in repr and str."""
    from pymomo.airtel.auth import AirtelAuth, AirtelTokenCache
    from pymomo.auth import _CachedToken

    cache = TokenCache()
    cache.set("collection", "super-secret-bearer-token", 3600)
    assert "super-secret-bearer-token" not in repr(cache)
    assert "super-secret-bearer-token" not in str(cache)

    entry = _CachedToken(access_token="super-secret-bearer-token", expires_at=9999.0)
    assert "super-secret-bearer-token" not in repr(entry)
    assert "access_token=<redacted>" in repr(entry)

    airtel_cache = AirtelTokenCache()
    airtel_cache.set("airtel-secret-token", 3600)
    assert "airtel-secret-token" not in repr(airtel_cache)
    assert "airtel-secret-token" not in str(airtel_cache)

    airtel_auth = AirtelAuth(
        client_id="cid",
        client_secret="airtel-client-secret-value",
        base_url="https://openapiuat.airtel.africa",
    )
    assert "airtel-client-secret-value" not in repr(airtel_auth)
    assert "airtel-client-secret-value" not in str(airtel_auth)
    assert "client_secret=<redacted>" in repr(airtel_auth)
