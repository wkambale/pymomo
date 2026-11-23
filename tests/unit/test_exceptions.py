from __future__ import annotations

import pytest

from py_momo_sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    MissingCredentialsError,
    PyMomoSDKError,
    PyMomoSDKServerError,
    ResourceNotFoundError,
    TransactionFailedError,
    WebhookVerificationError,
)


def test_exception_inheritance() -> None:
    """Verify that all exceptions inherit from PyMomoSDKError."""
    assert issubclass(AuthenticationError, PyMomoSDKError)
    assert issubclass(MissingCredentialsError, PyMomoSDKError)
    assert issubclass(BadRequestError, PyMomoSDKError)
    assert issubclass(ResourceNotFoundError, PyMomoSDKError)
    assert issubclass(ConflictError, PyMomoSDKError)
    assert issubclass(PyMomoSDKServerError, PyMomoSDKError)
    assert issubclass(TransactionFailedError, PyMomoSDKError)
    assert issubclass(WebhookVerificationError, PyMomoSDKError)


@pytest.mark.asyncio
async def test_missing_credentials_error_raised_on_unconfigured_products() -> None:
    """Verify sync and async clients raise MissingCredentialsError for unconfigured products."""
    from py_momo_sdk import AsyncPyMomoSDK, PyMomoSDK, PyMomoSDKConfig

    empty_cfg = PyMomoSDKConfig()
    with PyMomoSDK(empty_cfg) as sync_client:
        with pytest.raises(MissingCredentialsError, match="Collection credentials"):
            _ = sync_client.collection
        with pytest.raises(MissingCredentialsError, match="Disbursement credentials"):
            _ = sync_client.disbursement
        with pytest.raises(MissingCredentialsError, match="Remittance credentials"):
            _ = sync_client.remittance

    async with AsyncPyMomoSDK(empty_cfg) as async_client:
        with pytest.raises(MissingCredentialsError, match="Collection credentials"):
            _ = async_client.collection
        with pytest.raises(MissingCredentialsError, match="Disbursement credentials"):
            _ = async_client.disbursement
        with pytest.raises(MissingCredentialsError, match="Remittance credentials"):
            _ = async_client.remittance


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


def test_secret_redaction_and_error_sanitization_issue_81() -> None:
    """Verify telemetry path redaction, ProvisionResult, BcAuthorizeResponse, validate_reference_id, and BadRequestError (#81)."""
    import pytest

    from py_momo_sdk.http import _sanitize_telemetry_path
    from py_momo_sdk.models import BcAuthorizeResponse
    from py_momo_sdk.sandbox import ProvisionResult
    from py_momo_sdk.utils import validate_airtel_reference_id, validate_reference_id

    uid = "11111111-2222-4333-8444-555555555555"
    assert (
        _sanitize_telemetry_path(f"/v1_0/apiuser/{uid}") == "/v1_0/apiuser/<redacted>"
    )
    assert (
        _sanitize_telemetry_path(f"/v1_0/apiuser/{uid}/apikey")
        == "/v1_0/apiuser/<redacted>/apikey"
    )

    res = ProvisionResult(api_user=uid, api_key="secret-sandbox-key")
    assert res["api_user"] == uid
    assert res["api_key"] == "secret-sandbox-key"
    for rendered in (repr(res), str(res)):
        assert uid not in rendered
        assert "secret-sandbox-key" not in rendered
        assert "api_key=<redacted>" in rendered

    bc = BcAuthorizeResponse(auth_req_id="secret-auth-req-handle", expires_in=3600)
    for rendered in (repr(bc), str(bc)):
        assert "secret-auth-req-handle" not in rendered
        assert "auth_req_id=<redacted>" in rendered

    with pytest.raises(ValueError) as exc_ref:
        validate_reference_id("super_secret_api_key")
    assert "super_secret_api_key" not in str(exc_ref.value)

    with pytest.raises(ValueError) as exc_airtel:
        validate_airtel_reference_id("super_secret_key/with/slash")
    assert "super_secret_key" not in str(exc_airtel.value)

    injected_err = BadRequestError(
        "Line1\r\nFakeLog: admin=true\x00" + "A" * 1000,
        response_body={"secret": "should-not-appear-in-repr"},
    )
    assert "\r" not in str(injected_err)
    assert "\n" not in str(injected_err)
    assert "\x00" not in str(injected_err)
    assert len(str(injected_err)) <= 512
    assert "should-not-appear-in-repr" not in repr(injected_err)
