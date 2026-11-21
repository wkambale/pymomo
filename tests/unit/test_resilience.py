from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

import pytest
from pytest_httpx import HTTPXMock

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.config import PyMomoSDKConfig
from py_momo_sdk.exceptions import (
    PyMomoSDKError,
    PyMomoSDKServerError,
    WebhookVerificationError,
)
from py_momo_sdk.http import HttpClient
from py_momo_sdk.utils import (
    async_wait_for_settlement,
    detect_carrier_from_msisdn,
    wait_for_settlement,
)
from py_momo_sdk.webhooks import WebhookHandler


def test_http_client_retries_idempotent_requests(httpx_mock: HTTPXMock) -> None:
    """Verify HttpClient retries transient 503/429 for GET and X-Reference-Id POST."""
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        status_code=503,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        json={"availableBalance": "10.00", "currency": "EUR"},
        status_code=200,
    )

    with HttpClient(
        "https://sandbox.momodeveloper.mtn.com",
        10.0,
        max_retries=1,
        retry_backoff=0.001,
    ) as client:
        resp = client.request(
            "GET",
            "/collection/v1_0/account/balance",
            headers={"Authorization": "Bearer tok"},
        )
        assert resp.status_code == 200

    # Non-idempotent POST without X-Reference-Id must NOT retry
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay",
        status_code=503,
    )
    with (
        HttpClient(
            "https://sandbox.momodeveloper.mtn.com",
            10.0,
            max_retries=2,
            retry_backoff=0.001,
        ) as client,
        pytest.raises(PyMomoSDKServerError, match="503"),
    ):
        client.request(
            "POST",
            "/collection/v1_0/requesttopay",
            headers={"Authorization": "Bearer tok"},
            json={},
        )


@pytest.mark.asyncio
async def test_async_http_client_retries_with_reference_id(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify AsyncHttpClient retries POST carrying X-Reference-Id on 429."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay",
        status_code=429,
        headers={"Retry-After": "0.001"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay",
        status_code=202,
    )

    async with AsyncHttpClient(
        "https://sandbox.momodeveloper.mtn.com",
        10.0,
        max_retries=1,
        retry_backoff=0.001,
    ) as client:
        resp = await client.request(
            "POST",
            "/collection/v1_0/requesttopay",
            headers={
                "Authorization": "Bearer tok",
                "X-Reference-Id": "e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            },
            json={},
        )
        assert resp.status_code == 202


def test_config_retry_validation() -> None:
    """Verify PyMomoSDKConfig rejects invalid max_retries and retry_backoff."""
    with pytest.raises(ValueError, match="max_retries"):
        PyMomoSDKConfig(max_retries=-1)
    with pytest.raises(ValueError, match="max_retries"):
        PyMomoSDKConfig(max_retries=True)
    with pytest.raises(ValueError, match="retry_backoff"):
        PyMomoSDKConfig(retry_backoff=0.0)


def test_wait_for_settlement_sync_and_timeout() -> None:
    """Test wait_for_settlement resolves when status leaves pending and times out."""
    states = iter(
        [
            SimpleNamespace(is_pending=lambda: True, status="PENDING"),
            SimpleNamespace(is_pending=lambda: False, status="SUCCESSFUL"),
        ]
    )
    settled = wait_for_settlement(
        lambda: next(states),
        timeout=5.0,
        interval=0.001,
        sleep_fn=lambda _: None,
    )
    assert settled.status == "SUCCESSFUL"

    with pytest.raises(PyMomoSDKError, match="timed out"):
        wait_for_settlement(
            lambda: SimpleNamespace(is_pending=lambda: True, status="PENDING"),
            timeout=0.01,
            interval=0.005,
        )


@pytest.mark.asyncio
async def test_async_wait_for_settlement() -> None:
    """Test async_wait_for_settlement polls asynchronously until settled."""
    calls = 0

    async def poll() -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            is_pending=lambda: calls < 2,
            status="PENDING" if calls < 2 else "SUCCESSFUL",
        )

    async def noop_sleep(_: float) -> None:
        return None

    settled = await async_wait_for_settlement(
        poll, timeout=5.0, interval=0.001, sleep_fn=noop_sleep
    )
    assert settled.status == "SUCCESSFUL"
    assert calls == 2


def test_detect_carrier_from_msisdn() -> None:
    """Verify MSISDN carrier prefix inference across markets."""
    assert detect_carrier_from_msisdn("+256771234567") == ("UG", "mtn_momo")
    assert detect_carrier_from_msisdn("256751234567") == ("UG", "airtel_money")
    assert detect_carrier_from_msisdn("254712345678") == ("KE", "mpesa")
    assert detect_carrier_from_msisdn("221761234567") == ("SN", "wave")
    assert detect_carrier_from_msisdn("999000111") is None


def test_verify_timestamped_hmac_signature() -> None:
    """Test timestamped HMAC signature verification and replay tolerance."""
    payload = b'{"id":"cs_123","payment_status":"succeeded"}'
    secret = "whsec_wave_secret"
    ts = 1700000000
    sig = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    header = f"t={ts},v1={sig}"

    WebhookHandler.verify_timestamped_hmac_signature(
        payload, header, secret, tolerance_seconds=300, now=ts + 60
    )

    with pytest.raises(WebhookVerificationError, match="expired"):
        WebhookHandler.verify_timestamped_hmac_signature(
            payload, header, secret, tolerance_seconds=300, now=ts + 600
        )

    with pytest.raises(WebhookVerificationError, match="verification failed"):
        WebhookHandler.verify_timestamped_hmac_signature(
            b"tampered", header, secret, tolerance_seconds=300, now=ts + 10
        )

    with pytest.raises(WebhookVerificationError, match="Malformed"):
        WebhookHandler.verify_timestamped_hmac_signature(
            payload, "bad-header", secret, tolerance_seconds=300, now=ts
        )

    # Multi-v1 key rotation succeeds when any v1 signature matches
    rotated_header = f"t={ts},v1={'0' * 64},v1={sig}"
    WebhookHandler.verify_timestamped_hmac_signature(
        payload, rotated_header, secret, tolerance_seconds=300, now=ts + 5
    )

    # Unsupported algorithms, empty secrets, non-bytes payloads, bad tolerances, and future skew rejected
    for bad_alg in ("sha1", "md5"):
        with pytest.raises((ValueError, WebhookVerificationError)):
            WebhookHandler.verify_timestamped_hmac_signature(
                payload, header, secret, algorithm=bad_alg, now=ts
            )
    with pytest.raises(WebhookVerificationError):
        WebhookHandler.verify_timestamped_hmac_signature(
            payload, header, "", tolerance_seconds=300, now=ts
        )
    with pytest.raises((TypeError, WebhookVerificationError)):
        WebhookHandler.verify_timestamped_hmac_signature(
            "not-bytes", header, secret, tolerance_seconds=300, now=ts  # type: ignore[arg-type]
        )
    for bad_tol in (0, -10, float("inf")):
        with pytest.raises((TypeError, ValueError, WebhookVerificationError)):
            WebhookHandler.verify_timestamped_hmac_signature(
                payload, header, secret, tolerance_seconds=bad_tol, now=ts  # type: ignore[arg-type]
            )
    with pytest.raises(WebhookVerificationError):
        WebhookHandler.verify_timestamped_hmac_signature(
            payload, f"t={ts + 10000},v1={sig}", secret, tolerance_seconds=300, now=ts
        )
