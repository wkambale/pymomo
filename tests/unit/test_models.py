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
