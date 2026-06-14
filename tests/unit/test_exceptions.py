from __future__ import annotations

from pymomo.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    MomoServerError,
    PyMoMoError,
    ResourceNotFoundError,
    TransactionFailedError,
    WebhookVerificationError,
)


def test_exception_inheritance() -> None:
    """Verify that all exceptions inherit from PyMoMoError."""
    assert issubclass(AuthenticationError, PyMoMoError)
    assert issubclass(BadRequestError, PyMoMoError)
    assert issubclass(ResourceNotFoundError, PyMoMoError)
    assert issubclass(ConflictError, PyMoMoError)
    assert issubclass(MomoServerError, PyMoMoError)
    assert issubclass(TransactionFailedError, PyMoMoError)
    assert issubclass(WebhookVerificationError, PyMoMoError)


def test_bad_request_error_properties() -> None:
    """Verify BadRequestError stores the message and response body."""
    err = BadRequestError("Invalid format", response_body={"code": "BAD_FORMAT"})
    assert err.response_body == {"code": "BAD_FORMAT"}
    assert str(err) == "Invalid format"


def test_transaction_failed_error_format() -> None:
    """Verify TransactionFailedError formats failed messages correctly."""
    err = TransactionFailedError(reference_id="tx-123", reason="Insufficient funds")
    assert err.reference_id == "tx-123"
    assert err.reason == "Insufficient funds"
    assert str(err) == "Transaction tx-123 failed: Insufficient funds"
