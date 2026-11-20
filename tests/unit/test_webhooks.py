from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest

from py_momo_api.exceptions import WebhookVerificationError
from py_momo_api.models import TransactionStatus
from py_momo_api.webhooks import WebhookHandler


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
