from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest

from py_momo_sdk.exceptions import WebhookVerificationError
from py_momo_sdk.models import TransactionStatus
from py_momo_sdk.webhooks import WebhookHandler


def test_webhook_handler_parse() -> None:
    """Verify that WebhookHandler parses JSON dictionary callback into TransactionResult."""
    payload = {
        "financialTransactionId": "123456",
        "externalId": "ext-abc",
        "amount": "20.00",
        "currency": "EUR",
        "status": "SUCCESSFUL",
    }
    result = WebhookHandler.parse_transaction_notification(payload)
    assert result.financial_transaction_id == "123456"
    assert result.external_id == "ext-abc"
    assert result.status == TransactionStatus.successful
    assert result.is_successful() is True


def test_webhook_handler_parse_invalid_raises_verification_error() -> None:
    """Verify invalid or non-dict payloads raise WebhookVerificationError."""
    bad_body: Any = ["not", "a", "dict"]
    with pytest.raises(WebhookVerificationError, match="JSON object"):
        WebhookHandler.parse_transaction_notification(bad_body)

    with pytest.raises(WebhookVerificationError, match="Invalid webhook"):
        WebhookHandler.parse_transaction_notification({"status": "INVALID_STATUS"})


def test_webhook_handler_is_successful() -> None:
    """Verify WebhookHandler.is_successful return logic."""
    payload_ok = {"status": "SUCCESSFUL"}
    payload_fail = {"status": "FAILED"}
    assert WebhookHandler.is_successful(payload_ok) is True
    assert WebhookHandler.is_successful(payload_fail) is False


def test_webhook_verify_hmac_signature_valid() -> None:
    """Verify valid raw and prefixed HMAC-SHA256 and HMAC-SHA512 signatures pass."""
    payload = b'{"status":"SUCCESSFUL","amount":"100"}'
    secret = "super-secret-webhook-key"

    sig256 = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    WebhookHandler.verify_hmac_signature(payload, sig256, secret)
    WebhookHandler.verify_hmac_signature(payload, f"sha256={sig256}", secret)
    WebhookHandler.verify_hmac_signature(payload, f"SHA256={sig256.upper()}", secret)

    sig512 = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    WebhookHandler.verify_hmac_signature(
        payload, f"sha512={sig512}", secret, algorithm="sha512"
    )


def test_webhook_verify_hmac_signature_rejects_invalid() -> None:
    """Verify tampered payloads, wrong secrets, empty values, and weak algorithms fail."""
    payload = b'{"status":"SUCCESSFUL"}'
    secret = "super-secret-webhook-key"
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    # Tampered payload
    with pytest.raises(WebhookVerificationError, match="verification failed") as exc:
        WebhookHandler.verify_hmac_signature(b'{"status":"FAILED"}', sig, secret)
    assert secret not in str(exc.value)
    assert sig not in str(exc.value)

    # Wrong secret
    with pytest.raises(WebhookVerificationError):
        WebhookHandler.verify_hmac_signature(payload, sig, "wrong-secret")

    # Empty secret or signature
    with pytest.raises(WebhookVerificationError):
        WebhookHandler.verify_hmac_signature(payload, sig, "")
    with pytest.raises(WebhookVerificationError):
        WebhookHandler.verify_hmac_signature(payload, "", secret)

    # Unsupported / weak algorithms
    with pytest.raises(WebhookVerificationError, match="Unsupported"):
        WebhookHandler.verify_hmac_signature(payload, sig, secret, algorithm="sha1")
    with pytest.raises(WebhookVerificationError, match="Unsupported"):
        WebhookHandler.verify_hmac_signature(payload, sig, secret, algorithm="md5")

    # Non-bytes payload
    bad_payload: Any = "not-bytes"
    with pytest.raises(WebhookVerificationError, match="must be bytes"):
        WebhookHandler.verify_hmac_signature(bad_payload, sig, secret)


def test_webhook_verify_source_ip() -> None:
    """Verify source IP allowlist validation for IPv4, IPv6, and fail-closed errors."""
    WebhookHandler.verify_source_ip("196.201.214.42", ["196.201.214.0/24"])
    WebhookHandler.verify_source_ip("2001:db8::1", ["2001:db8::/32"])
    WebhookHandler.verify_source_ip(
        "203.0.113.10", ["2001:db8::/32", "203.0.113.10/32"]
    )

    # Disallowed IP
    with pytest.raises(WebhookVerificationError, match="not in allowed networks"):
        WebhookHandler.verify_source_ip("198.51.100.5", ["196.201.214.0/24"])

    # Empty allowlist fails closed
    with pytest.raises(WebhookVerificationError, match="must not be empty"):
        WebhookHandler.verify_source_ip("196.201.214.42", [])

    # Malformed IP or CIDR
    with pytest.raises(WebhookVerificationError, match="Invalid webhook source IP"):
        WebhookHandler.verify_source_ip("not-an-ip", ["196.201.214.0/24"])
    with pytest.raises(WebhookVerificationError, match="Invalid CIDR"):
        WebhookHandler.verify_source_ip("196.201.214.42", ["not-a-cidr"])

    # IPv4-mapped IPv6 matches IPv4 CIDR; trailing invalid CIDR & host-bit typos rejected
    WebhookHandler.verify_source_ip("::ffff:196.201.214.42", ["196.201.214.0/24"])
    with pytest.raises(WebhookVerificationError, match="Invalid CIDR"):
        WebhookHandler.verify_source_ip(
            "196.201.214.42", ["196.201.214.0/24", "not-a-cidr"]
        )
    with pytest.raises(WebhookVerificationError, match="Invalid CIDR"):
        WebhookHandler.verify_source_ip("196.201.214.42", ["196.201.214.42/8"])
    with pytest.raises(WebhookVerificationError):
        WebhookHandler.verify_source_ip("196.201.214.42", "196.201.214.0/24")


def test_webhook_non_ascii_and_timestamped_replay_hardening() -> None:
    """Verify non-ASCII signatures raise WebhookVerificationError and replay edge cases fail closed."""
    payload = b'{"status":"SUCCESSFUL"}'
    secret = "whsec_test"

    # Non-ASCII signature characters must raise WebhookVerificationError, never TypeError
    with pytest.raises(WebhookVerificationError):
        WebhookHandler.verify_hmac_signature(payload, "é-non-ascii", secret)
    with pytest.raises(WebhookVerificationError):
        WebhookHandler.verify_timestamped_hmac_signature(
            payload, "t=1700000000,v1=é-non-ascii", secret, now=1700000000
        )

    # Valid timestamped signature
    valid_sig = hmac.new(
        secret.encode(), b"1700000000." + payload, hashlib.sha256
    ).hexdigest()
    WebhookHandler.verify_timestamped_hmac_signature(
        payload, f"t=1700000000,v1={valid_sig}", secret, now=1700000010
    )

    # NaN / inf / bool tolerance_seconds or now rejected
    for bad_tol in (float("nan"), float("inf"), 0, -5, True):
        with pytest.raises(WebhookVerificationError):
            WebhookHandler.verify_timestamped_hmac_signature(
                payload,
                f"t=1700000000,v1={valid_sig}",
                secret,
                tolerance_seconds=bad_tol,
                now=1700000000,
            )
    with pytest.raises(WebhookVerificationError):
        WebhookHandler.verify_timestamped_hmac_signature(
            payload, f"t=1700000000,v1={valid_sig}", secret, now=float("nan")
        )

    # Duplicate t=, leading-zero timestamp, and future timestamp rejected
    with pytest.raises(WebhookVerificationError, match="Duplicate timestamp"):
        WebhookHandler.verify_timestamped_hmac_signature(
            payload,
            f"t=1700000000,t=1700000000,v1={valid_sig}",
            secret,
            now=1700000000,
        )
    with pytest.raises(WebhookVerificationError, match="Invalid timestamp"):
        WebhookHandler.verify_timestamped_hmac_signature(
            payload, f"t=01700000000,v1={valid_sig}", secret, now=1700000000
        )
    future_sig = hmac.new(
        secret.encode(), b"1700000500." + payload, hashlib.sha256
    ).hexdigest()
    with pytest.raises(WebhookVerificationError, match="future"):
        WebhookHandler.verify_timestamped_hmac_signature(
            payload,
            f"t=1700000500,v1={future_sig}",
            secret,
            tolerance_seconds=3600,
            now=1700000000,
        )
