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


def test_structured_error_fields_and_response_body_redaction_issue_116() -> None:
    """Verify PyMomoSDKError exposes structured metadata and redacts secrets in response_body (#116)."""
    raw_body = {
        "code": "INVALID_CALLBACK_URL_HOST",
        "message": "Callback URL host does not match provider",
        "access_token": "live-jwt-token",
        "nested": {
            "client_secret": "top-secret-val",
            "apiKey": "my-api-key",
            "safe_detail": "currency=UGX",
        },
        "items": [{"pin": "1234", "field": "amount"}],
    }
    err = BadRequestError(
        "INVALID_CALLBACK_URL_HOST: Callback URL host does not match provider",
        response_body=raw_body,
        reference_id="ref-123",
        status_code=422,
        error_code="INVALID_CALLBACK_URL_HOST",
        reason="Callback URL host does not match provider",
        provider="MTN MoMo",
    )
    assert err.reference_id == "ref-123"
    assert err.status_code == 422
    assert err.error_code == "INVALID_CALLBACK_URL_HOST"
    assert err.reason == "Callback URL host does not match provider"
    assert err.provider == "MTN MoMo"
    assert err.response_body["access_token"] == "<redacted>"
    assert err.response_body["nested"]["client_secret"] == "<redacted>"
    assert err.response_body["nested"]["apiKey"] == "<redacted>"
    assert err.response_body["nested"]["safe_detail"] == "currency=UGX"
    assert err.response_body["items"][0]["pin"] == "<redacted>"
    assert err.response_body["items"][0]["field"] == "amount"

    rendered = repr(err)
    assert "BadRequestError(" in rendered
    assert "reference_id='ref-123'" in rendered
    assert "status_code=422" in rendered
    assert "error_code='INVALID_CALLBACK_URL_HOST'" in rendered
    assert "provider='MTN MoMo'" in rendered
    assert "live-jwt-token" not in rendered
    assert "top-secret-val" not in rendered
    assert "currency=UGX" not in rendered  # response_body omitted from repr

    conflict = ConflictError(
        "Duplicate X-Reference-Id",
        reference_id="dup-1",
        error_code="DUPLICATE_REFERENCE",
        reason="Reference already exists",
        provider="MTN MoMo",
    )
    assert conflict.status_code == 409
    assert conflict.reference_id == "dup-1"
    assert conflict.error_code == "DUPLICATE_REFERENCE"

    failed = TransactionFailedError(
        reference_id="tx-999",
        reason="Insufficient balance",
        status_code=200,
        error_code="DP00800001001",
        provider="Airtel Money",
        response_body={"status": {"result_code": "DP00800001001"}},
    )
    assert failed.reference_id == "tx-999"
    assert failed.status_code == 200
    assert failed.error_code == "DP00800001001"
    assert failed.provider == "Airtel Money"
    assert failed.reason == "Insufficient balance"
