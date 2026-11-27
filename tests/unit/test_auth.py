from __future__ import annotations

import pytest

from py_momo_sdk.auth import TokenCache


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


def test_token_cache_safety_margin_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify proportional safety margin for short TTLs, 30s cap for long TTLs, and overflow/namespace guards (#82)."""
    import py_momo_sdk.auth as auth_mod

    now = [1000.0]
    monkeypatch.setattr(auth_mod.time, "monotonic", lambda: now[0])

    cache = TokenCache()
    # Short TTL (30s): 20% margin -> valid for 24s (not evicted immediately!)
    cache.set("collection", "short-tok", 30)
    assert cache.get("collection") == "short-tok"
    now[0] = 1023.9
    assert cache.get("collection") == "short-tok"
    now[0] = 1024.0
    assert cache.get("collection") is None

    # Long TTL (3600s): capped at 30s safety margin -> expires at 3570s
    now[0] = 2000.0
    cache.set("collection", "long-tok", 3600)
    now[0] = 5569.9
    assert cache.get("collection") == "long-tok"
    now[0] = 5570.0
    assert cache.get("collection") is None

    # Huge expires_in does not raise OverflowError
    cache.set("collection", "huge-tok", 10**400)
    assert cache.get("collection") == "huge-tok"

    # Namespace isolation prevents cross-tenant/cross-environment token reuse
    cache.set("collection", "sandbox-tok", 3600, namespace="sandbox:https://sb")
    cache.set("collection", "prod-tok", 3600, namespace="prod:https://pr")
    assert cache.get("collection", namespace="sandbox:https://sb") == "sandbox-tok"
    assert cache.get("collection", namespace="prod:https://pr") == "prod-tok"

    # Invalid inputs rejected
    with pytest.raises(ValueError, match="access_token"):
        cache.set("collection", "   ", 60)
    with pytest.raises(ValueError, match="expires_in"):
        cache.set("collection", "tok", 0)
    with pytest.raises(ValueError, match="expires_in"):
        cache.set("collection", "tok", True)  # type: ignore[arg-type]


def test_token_cache_and_airtel_auth_redaction() -> None:
    """Verify token caches and AirtelAuth redact secrets in repr and str."""
    from py_momo_sdk.airtel.auth import AirtelAuth, AirtelTokenCache
    from py_momo_sdk.auth import _CachedToken

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


def test_conditional_token_invalidation_prevents_stale_eviction() -> None:
    """Verify expected_token prevents a stale 401 from evicting a fresh token."""
    from py_momo_sdk.airtel.auth import AirtelTokenCache

    cache = TokenCache()
    cache.set("collection", "fresh-token", 3600)
    # Stale 401 with old-token must NOT evict fresh-token
    cache.invalidate("collection", expected_token="old-token")
    assert cache.get("collection") == "fresh-token"
    # Matching expected_token DOES evict it
    cache.invalidate("collection", expected_token="fresh-token")
    assert cache.get("collection") is None

    airtel_cache = AirtelTokenCache()
    airtel_cache.set("airtel-fresh", 3600)
    airtel_cache.invalidate(expected_token="airtel-old")
    assert airtel_cache.get() == "airtel-fresh"
    airtel_cache.invalidate(expected_token="airtel-fresh")
    assert airtel_cache.get() is None


def test_issue_126_token_cache_no_namespace_delimiter_collision() -> None:
    """Verify Issue #126: distinct (namespace, product) tuples never collide on ':'."""
    cache = TokenCache()
    cache.set("c", "tok-left", 3600, namespace="a:b")
    cache.set("b:c", "tok-right", 3600, namespace="a")
    cache.set("a:b", "tok-root", 3600, namespace="")

    assert cache.get("c", namespace="a:b") == "tok-left"
    assert cache.get("b:c", namespace="a") == "tok-right"
    assert cache.get("a:b", namespace="") == "tok-root"

    cache.invalidate("c", namespace="a:b")
    assert cache.get("c", namespace="a:b") is None
    assert cache.get("b:c", namespace="a") == "tok-right"
    assert cache.get("a:b", namespace="") == "tok-root"
