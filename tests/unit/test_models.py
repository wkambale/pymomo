from __future__ import annotations

import pytest

from py_momo_sdk.models import (
    Party,
    RequestToPayRequest,
    TransactionResult,
    TransactionStatus,
)


def test_party_parsing_and_serialization() -> None:
    """Verify Party parses both camelCase and snake_case keys and serializes with alias."""
    p1 = Party(party_id_type="MSISDN", party_id="1234")
    assert p1.party_id_type == "MSISDN"

    dump = p1.model_dump(by_alias=True)
    assert dump == {"partyIdType": "MSISDN", "partyId": "1234"}

    p2 = Party.model_validate({"partyIdType": "EMAIL", "partyId": "test"})
    assert p2.party_id_type == "EMAIL"
    assert p2.party_id == "test"


def test_request_to_pay_serialization() -> None:
    """Verify RequestToPayRequest serializes its nested models using alias names."""
    req = RequestToPayRequest(
        amount="100",
        currency="EUR",
        external_id="ext-1",
        payer=Party(party_id_type="MSISDN", party_id="1234"),
    )
    dump = req.model_dump(by_alias=True)
    assert dump["externalId"] == "ext-1"
    assert dump["payer"]["partyId"] == "1234"


def test_transaction_result_helpers() -> None:
    """Verify that TransactionResult is_successful, is_pending, and is_failed return correct booleans."""
    r_success = TransactionResult(status=TransactionStatus.successful)
    assert r_success.is_successful() is True
    assert r_success.is_pending() is False
    assert r_success.is_failed() is False

    r_pending = TransactionResult(status=TransactionStatus.pending)
    assert r_pending.is_successful() is False
    assert r_pending.is_pending() is True
    assert r_pending.is_failed() is False

    r_failed = TransactionResult(status=TransactionStatus.failed)
    assert r_failed.is_successful() is False
    assert r_failed.is_pending() is False
    assert r_failed.is_failed() is True


def test_secret_models_redact_credentials_in_repr_and_str() -> None:
    """Verify TokenResponse and ApiKeyResult never expose secrets in repr or str."""
    from py_momo_sdk.models import ApiKeyResult, TokenResponse

    tok = TokenResponse(
        access_token="very-secret-jwt-token",
        token_type="access_token",
        expires_in=3600,
    )
    assert "very-secret-jwt-token" not in repr(tok)
    assert "very-secret-jwt-token" not in str(tok)
    assert "access_token=<redacted>" in repr(tok)

    key = ApiKeyResult(apiKey="very-secret-api-key")
    assert "very-secret-api-key" not in repr(key)
    assert "very-secret-api-key" not in str(key)
    assert "api_key=<redacted>" in repr(key)

    from py_momo_sdk import OAuth2TokenResponse

    oauth = OAuth2TokenResponse(
        access_token="oauth-secret-access",
        token_type="Bearer",
        expires_in=3600,
        scope="profile",
        refresh_token="oauth-secret-refresh",
    )
    assert "oauth-secret-access" not in repr(oauth)
    assert "oauth-secret-access" not in str(oauth)
    assert "oauth-secret-refresh" not in repr(oauth)
    assert "oauth-secret-refresh" not in str(oauth)
    assert "access_token=<redacted>" in repr(oauth)
    assert "refresh_token=<redacted>" in repr(oauth)

    import pytest
    from pydantic import ValidationError

    for bad_token in ("", "   ", "tok\r\n"):
        with pytest.raises(ValidationError):
            TokenResponse(access_token=bad_token, token_type="Bearer", expires_in=3600)
    for bad_exp in (0, -10, True, False, "-5", "0", -5.0, 0.0, 1.5, "\u0665"):
        with pytest.raises(ValidationError):
            TokenResponse(
                access_token="valid", token_type="Bearer", expires_in=bad_exp  # type: ignore[arg-type]
            )
        with pytest.raises(ValidationError):
            OAuth2TokenResponse(
                access_token="valid", token_type="Bearer", expires_in=bad_exp  # type: ignore[arg-type]
            )

    from py_momo_sdk.models import BcAuthorizeResponse

    for bad_exp in (0, -5, True, "-5", 1.5):
        with pytest.raises(ValidationError):
            BcAuthorizeResponse(auth_req_id="req-1", expires_in=bad_exp)  # type: ignore[arg-type]

    for bad_secret in ("", "   ", "bad\r\nkey"):
        with pytest.raises(ValidationError):
            ApiKeyResult(apiKey=bad_secret)
        with pytest.raises(ValidationError):
            OAuth2TokenResponse(
                access_token="valid",
                token_type="Bearer",
                expires_in=3600,
                refresh_token=bad_secret,
            )


def test_request_models_validate_amount_and_currency() -> None:
    """Verify payment models reject zero, negative, non-finite, or non-numeric amounts."""
    import pytest
    from pydantic import ValidationError

    from py_momo_sdk.airtel.models import (
        AirtelDisbursementPayee,
        AirtelDisbursementRequest,
        AirtelDisbursementTransaction,
    )

    # Verify a valid nested AirtelDisbursementRequest succeeds before testing invalid amounts
    valid_airtel = AirtelDisbursementRequest(
        payee=AirtelDisbursementPayee(msisdn="751234567"),
        reference="ref-valid-1",
        pin="1234",
        transaction=AirtelDisbursementTransaction(amount="1000", id="tx-valid-1"),
    )
    assert valid_airtel.transaction.amount == "1000"

    for bad_amount in ("", "0", "0.00", "-10", "+10", "NaN", "Infinity", "1e5", "abc"):
        with pytest.raises(ValidationError):
            RequestToPayRequest(
                amount=bad_amount,
                currency="UGX",
                external_id="ext-1",
                payer=Party(party_id_type="MSISDN", party_id="256771234567"),
            )
        with pytest.raises(ValidationError, match="Amount"):
            AirtelDisbursementRequest(
                payee=AirtelDisbursementPayee(msisdn="751234567"),
                reference="ref-1",
                pin="1234",
                transaction=AirtelDisbursementTransaction(
                    amount=bad_amount, id="tx-bad-1"
                ),
            )

    with pytest.raises(ValidationError):
        RequestToPayRequest(
            amount="100.00",
            currency="../bad",
            external_id="ext-1",
            payer=Party(party_id_type="MSISDN", party_id="256771234567"),
        )

    for bad_ext_id in ("", "   ", "ext\r\ninjected"):
        with pytest.raises(ValidationError):
            RequestToPayRequest(
                amount="100.00",
                currency="UGX",
                external_id=bad_ext_id,
                payer=Party(party_id_type="MSISDN", party_id="256771234567"),
            )


def test_mtn_error_reason_models_amount_polling_and_env_issue_83(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify MTN ErrorReason dict parsing, strict amounts, model guards, polling, and from_env (#83)."""
    from pydantic import ValidationError

    from py_momo_sdk import (
        MTN_RWANDA,
        PyMomoSDKConfig,
        TransactionFailedError,
        wait_for_settlement,
    )
    from py_momo_sdk.exceptions import PyMomoSDKError
    from py_momo_sdk.models import (
        BcAuthorizeResponse,
        OAuth2TokenResponse,
        RefundRequest,
        TransactionResult,
        TransactionStatus,
    )
    from py_momo_sdk.utils import validate_amount

    # 1. TransactionResult handles MTN ErrorReason JSON objects
    res = TransactionResult.model_validate(
        {
            "status": "FAILED",
            "reason": {
                "code": "NOT_ENOUGH_FUNDS",
                "message": "Insufficient funds",
            },
        }
    )
    assert res.status == TransactionStatus.failed
    assert res.reason == "NOT_ENOUGH_FUNDS: Insufficient funds"
    assert res.reason_code == "NOT_ENOUGH_FUNDS"

    # 2. Strict amount validation (no leading zeros, sub-cent dust, unbounded digits, zero-decimal fractions)
    for bad in ("000100", "00.50", "0.000001", "100.999", "9" * 100):
        with pytest.raises(ValueError, match="Amount"):
            validate_amount(bad)
    with pytest.raises(ValueError, match="zero-decimal"):
        validate_amount("100.50", currency="UGX")
    assert validate_amount("100.00", currency="UGX") == "100.00"
    assert validate_amount("100.50", currency="EUR") == "100.50"

    # 3. Party, note length/control chars, RefundRequest UUID, OAuth2/BcAuthorize bounds
    with pytest.raises(ValidationError):
        Party(partyIdType="", partyId="")
    with pytest.raises(ValidationError):
        RefundRequest(
            amount="10",
            currency="EUR",
            externalId="ext-1",
            referenceIdToRefund="not-a-uuid",
        )
    with pytest.raises(ValidationError):
        RequestToPayRequest(
            amount="10",
            currency="EUR",
            externalId="ext-1",
            payer=Party(partyIdType="MSISDN", partyId="256771234567"),
            payerMessage="hi\r\n\x00there",
        )
    with pytest.raises(ValidationError):
        RequestToPayRequest(
            amount="10",
            currency="EUR",
            externalId="ext-1",
            payer=Party(partyIdType="MSISDN", partyId="256771234567"),
            payeeNote="x" * 161,
        )
    with pytest.raises(ValidationError):
        OAuth2TokenResponse(
            access_token="a",
            token_type="b",
            expires_in=60,
            refresh_token_expired_in=-5,
        )
    with pytest.raises(ValidationError):
        BcAuthorizeResponse(auth_req_id="   ", expires_in=60, interval=5)
    with pytest.raises(ValidationError):
        BcAuthorizeResponse(auth_req_id="req-1", expires_in=60, interval=-1)

    # 4. wait_for_settlement handles pending dicts, never polls past deadline, and supports raise_on_failed
    dict_polls = [{"status": "pending"}, {"status": "SUCCESSFUL"}]
    idx = 0

    def _poll_dict() -> dict[str, str]:
        nonlocal idx
        out = dict_polls[idx]
        idx += 1
        return out

    settled = wait_for_settlement(
        _poll_dict, timeout=5.0, interval=0.01, sleep_fn=lambda _: None
    )
    assert settled["status"] == "SUCCESSFUL"
    assert idx == 2

    calls = 0

    def _always_pending() -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"status": "PENDING"}

    with pytest.raises(PyMomoSDKError, match="timed out"):
        wait_for_settlement(
            _always_pending, timeout=0.05, interval=0.1, max_interval=0.1
        )
    assert calls == 1  # Never sleeps past deadline to fire an extra poll!

    with pytest.raises(TransactionFailedError, match="NOT_ENOUGH_FUNDS"):
        wait_for_settlement(lambda: res, timeout=1.0, raise_on_failed=True)

    # 5. MTN_RWANDA constant and PyMomoSDKConfig.from_env() retry/backoff/whitespace handling
    assert MTN_RWANDA == "mtnrwanda"
    monkeypatch.setenv("PY_MOMO_SDK_ENVIRONMENT", "  mtnrwanda  ")
    monkeypatch.setenv("PY_MOMO_SDK_MAX_RETRIES", "3")
    monkeypatch.setenv("PY_MOMO_SDK_RETRY_BACKOFF", "0.25")
    monkeypatch.setenv("PY_MOMO_SDK_BASE_URL", "   ")
    cfg = PyMomoSDKConfig.from_env()
    assert cfg.environment == "mtnrwanda"
    assert cfg.max_retries == 3
    assert cfg.retry_backoff == 0.25
