from __future__ import annotations

from py_momo_api.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    PyMomoAPIError,
    PyMomoAPIServerError,
    ResourceNotFoundError,
    TransactionFailedError,
    WebhookVerificationError,
)


def test_exception_inheritance() -> None:
    """Verify that all exceptions inherit from PyMomoAPIError."""
    assert issubclass(AuthenticationError, PyMomoAPIError)
    assert issubclass(BadRequestError, PyMomoAPIError)
    assert issubclass(ResourceNotFoundError, PyMomoAPIError)
    assert issubclass(ConflictError, PyMomoAPIError)
    assert issubclass(PyMomoAPIServerError, PyMomoAPIError)
    assert issubclass(TransactionFailedError, PyMomoAPIError)
    assert issubclass(WebhookVerificationError, PyMomoAPIError)


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
