from __future__ import annotations

from pymomo.models import (
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
    from pymomo.models import ApiKeyResult, TokenResponse

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


def test_request_models_validate_amount_and_currency() -> None:
    """Verify payment models reject zero, negative, non-finite, or non-numeric amounts."""
    import pytest
    from pydantic import ValidationError

    from pymomo.airtel.models import AirtelDisbursementRequest

    for bad_amount in ("", "0", "0.00", "-10", "+10", "NaN", "Infinity", "1e5", "abc"):
        with pytest.raises(ValidationError):
            RequestToPayRequest(
                amount=bad_amount,
                currency="UGX",
                external_id="ext-1",
                payer=Party(party_id_type="MSISDN", party_id="256771234567"),
            )
        with pytest.raises(ValidationError):
            AirtelDisbursementRequest(
                amount=bad_amount,
                number="256771234567",
                reference="ref-1",
                pin="1234",
            )

    with pytest.raises(ValidationError):
        RequestToPayRequest(
            amount="100.00",
            currency="../bad",
            external_id="ext-1",
            payer=Party(party_id_type="MSISDN", party_id="256771234567"),
        )
