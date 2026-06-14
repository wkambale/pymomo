from __future__ import annotations

from pymomo.models import TransactionStatus
from pymomo.webhooks import WebhookHandler


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


def test_webhook_handler_is_successful() -> None:
    """Verify WebhookHandler.is_successful return logic."""
    payload_ok = {
        "status": "SUCCESSFUL",
    }
    payload_fail = {
        "status": "FAILED",
    }
    assert WebhookHandler.is_successful(payload_ok) is True
    assert WebhookHandler.is_successful(payload_fail) is False
