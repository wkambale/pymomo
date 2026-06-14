from __future__ import annotations

from typing import Any

from pymomo.models import TransactionResult


class WebhookHandler:
    """Utilities for processing MoMo webhook callbacks."""

    @staticmethod
    def parse_transaction_notification(body: dict[str, Any]) -> TransactionResult:
        """Parse a webhook callback body into a TransactionResult model."""
        return TransactionResult.model_validate(body)

    @staticmethod
    def is_successful(body: dict[str, Any]) -> bool:
        """Check if a webhook callback body indicates a successful transaction."""
        result = WebhookHandler.parse_transaction_notification(body)
        return result.is_successful()
