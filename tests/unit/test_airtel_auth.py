from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from py_momo_sdk.airtel.auth import AirtelAuth, AirtelTokenCache
from py_momo_sdk.exceptions import AuthenticationError, PyMomoSDKError


def test_airtel_token_cache_get_set_invalidate() -> None:
    """Verify standard set, get, and invalidate behaviors on AirtelTokenCache."""
    cache = AirtelTokenCache()

    assert cache.get() is None

    cache.set("airtel-token-1", 3600)
    assert cache.get() == "airtel-token-1"

    cache.invalidate()
    assert cache.get() is None


def test_airtel_token_cache_safety_margin_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify proportional safety margin for short TTLs and 30s cap for long TTLs (#84)."""
    import py_momo_sdk.airtel.auth as airtel_auth_mod

    now = [1000.0]
    monkeypatch.setattr(airtel_auth_mod.time, "monotonic", lambda: now[0])

    cache = AirtelTokenCache()
    # Short TTL (30s): 20% margin -> valid for 24s (not evicted immediately)
    cache.set("airtel-short", 30)
    assert cache.get() == "airtel-short"
    now[0] = 1023.9
    assert cache.get() == "airtel-short"
    now[0] = 1024.0
    assert cache.get() is None

    # Long TTL (3600s): 30s safety margin
    now[0] = 2000.0
    cache.set("airtel-long", 3600)
    now[0] = 5569.9
    assert cache.get() == "airtel-long"
    now[0] = 5570.0
    assert cache.get() is None


def test_airtel_auth_get_token_success(httpx_mock: HTTPXMock) -> None:
    """Verify successful authentication and token caching."""
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "secret-token", "expires_in": 3600},
        status_code=200,
    )

    auth = AirtelAuth(
        client_id="my-client-id",
        client_secret="my-client-secret",
        base_url="https://openapiuat.airtel.africa",
    )

    with httpx.Client(base_url="https://openapiuat.airtel.africa") as client:
        # First call fetches token from API
        token = auth.get_token(client)
        assert token == "secret-token"

        # Second call returns cached token
        token2 = auth.get_token(client)
        assert token2 == "secret-token"


def test_airtel_auth_get_token_401(httpx_mock: HTTPXMock) -> None:
    """Verify that HTTP 401 raises AuthenticationError."""
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        status_code=401,
    )

    auth = AirtelAuth(
        client_id="my-client-id",
        client_secret="my-client-secret",
        base_url="https://openapiuat.airtel.africa",
    )

    with httpx.Client(base_url="https://openapiuat.airtel.africa") as client:
        with pytest.raises(AuthenticationError) as excinfo:
            auth.get_token(client)
        assert "Invalid or expired Airtel client credentials" in str(excinfo.value)


def test_airtel_auth_get_token_error_status(httpx_mock: HTTPXMock) -> None:
    """Verify that HTTP error status >= 400 raises AuthenticationError."""
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        status_code=500,
    )

    auth = AirtelAuth(
        client_id="my-client-id",
        client_secret="my-client-secret",
        base_url="https://openapiuat.airtel.africa",
    )

    with httpx.Client(base_url="https://openapiuat.airtel.africa") as client:
        with pytest.raises(AuthenticationError) as excinfo:
            auth.get_token(client)
        assert "Airtel authentication failed: HTTP 500" in str(excinfo.value)


def test_airtel_auth_get_token_invalid_response(httpx_mock: HTTPXMock) -> None:
    """Verify that invalid response format raises AuthenticationError."""
    # Missing access_token
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"expires_in": 3600},
        status_code=200,
    )

    auth = AirtelAuth(
        client_id="my-client-id",
        client_secret="my-client-secret",
        base_url="https://openapiuat.airtel.africa",
    )

    with httpx.Client(base_url="https://openapiuat.airtel.africa") as client:
        with pytest.raises(AuthenticationError) as excinfo:
            auth.get_token(client)
        assert "Airtel OAuth response did not contain token data" in str(excinfo.value)


def test_airtel_auth_get_token_exceptions() -> None:
    """Verify connection or timeout issues raise PyMomoSDKError."""
    auth = AirtelAuth(
        client_id="my-client-id",
        client_secret="my-client-secret",
        base_url="https://openapiuat.airtel.africa",
    )

    with httpx.Client(base_url="https://openapiuat.airtel.africa") as client:
        with patch.object(
            client, "send", side_effect=httpx.TimeoutException("timeout")
        ):
            with pytest.raises(PyMomoSDKError) as excinfo:
                auth.get_token(client)
            assert "Airtel authentication request timed out" in str(excinfo.value)

        with patch.object(client, "send", side_effect=httpx.RequestError("conn")):
            with pytest.raises(PyMomoSDKError) as excinfo:
                auth.get_token(client)
            assert "Airtel authentication request connection error" in str(
                excinfo.value
            )


def test_airtel_auth_handles_malformed_json_and_expiry(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify non-JSON, non-dict, and invalid expires_in raise AuthenticationError."""
    auth = AirtelAuth(
        client_id="my-client-id",
        client_secret="my-client-secret",
        base_url="https://openapiuat.airtel.africa",
    )

    with httpx.Client(base_url="https://openapiuat.airtel.africa") as client:
        httpx_mock.add_response(
            method="POST",
            url="https://openapiuat.airtel.africa/auth/oauth2/token",
            text="<html>Bad Gateway</html>",
            status_code=200,
        )
        with pytest.raises(AuthenticationError, match="not valid JSON"):
            auth.get_token(client)

        httpx_mock.add_response(
            method="POST",
            url="https://openapiuat.airtel.africa/auth/oauth2/token",
            json=["not", "a", "dict"],
            status_code=200,
        )
        with pytest.raises(AuthenticationError, match="did not contain token data"):
            auth.get_token(client)

        httpx_mock.add_response(
            method="POST",
            url="https://openapiuat.airtel.africa/auth/oauth2/token",
            json={"access_token": "tok", "expires_in": "not-an-int"},
            status_code=200,
        )
        with pytest.raises(AuthenticationError, match="invalid expires_in"):
            auth.get_token(client)

        httpx_mock.add_response(
            method="POST",
            url="https://openapiuat.airtel.africa/auth/oauth2/token",
            json={"access_token": "tok", "expires_in": True},
            status_code=200,
        )
        with pytest.raises(AuthenticationError, match="invalid expires_in"):
            auth.get_token(client)


def test_airtel_token_cache_thread_safety() -> None:
    """Verify AirtelTokenCache uses a lock and handles concurrent access safely."""
    import threading

    cache = AirtelTokenCache()
    errors: list[Exception] = []

    def worker(idx: int) -> None:
        try:
            for step in range(50):
                cache.set(f"tok-{idx}-{step}", 3600)
                _ = cache.get()
                if step % 10 == 0:
                    cache.invalidate()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
