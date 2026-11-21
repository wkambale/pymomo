from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from py_momo_sdk.utils import validate_amount, validate_callback_url, validate_currency


class NormalizedStatus(str, Enum):
    """Canonical transaction status across all payment providers."""

    INITIATED = "INITIATED"
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    REVERSED = "REVERSED"


class ProviderCapabilities(BaseModel):
    """Declarative capability metadata for a payment provider adapter."""

    model_config = ConfigDict(extra="ignore")

    provider_id: str
    supports_collection: bool = True
    supports_disbursement: bool = True
    supports_balance: bool = True
    supports_webhook_hmac: bool = False
    currencies: tuple[str, ...] = ()


class PaymentRequest(BaseModel):
    """Normalized collection payment request."""

    model_config = ConfigDict(extra="ignore")

    amount: str
    currency: str
    payer_msisdn: str
    external_id: str = ""
    payer_message: str = ""
    payee_note: str = ""
    reference_id: str | None = None
    callback_url: str | None = None

    @field_validator("amount")
    @classmethod
    def _check_amount(cls, value: str) -> str:
        return validate_amount(value)

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, value: str) -> str:
        return validate_currency(value)

    @field_validator("callback_url")
    @classmethod
    def _check_callback_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_callback_url(value)


class DisbursementRequest(BaseModel):
    """Normalized disbursement payout request."""

    model_config = ConfigDict(extra="ignore")

    amount: str
    currency: str
    payee_msisdn: str
    external_id: str = ""
    payer_message: str = ""
    payee_note: str = ""
    reference_id: str | None = None
    callback_url: str | None = None

    @field_validator("amount")
    @classmethod
    def _check_amount(cls, value: str) -> str:
        return validate_amount(value)

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, value: str) -> str:
        return validate_currency(value)

    @field_validator("callback_url")
    @classmethod
    def _check_callback_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_callback_url(value)


class PaymentResult(BaseModel):
    """Normalized response for collections, disbursements, and status queries."""

    model_config = ConfigDict(extra="ignore")

    provider: str
    reference_id: str
    status: NormalizedStatus
    amount: str | None = None
    currency: str | None = None
    provider_transaction_id: str | None = None
    external_id: str | None = None
    checkout_url: str | None = None
    reason: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    def is_successful(self) -> bool:
        """Return True if the transaction settled successfully."""
        return self.status == NormalizedStatus.SUCCEEDED

    def is_pending(self) -> bool:
        """Return True if the transaction is still awaiting settlement."""
        return self.status in (NormalizedStatus.INITIATED, NormalizedStatus.PENDING)

    def is_failed(self) -> bool:
        """Return True if the transaction failed or expired."""
        return self.status in (NormalizedStatus.FAILED, NormalizedStatus.EXPIRED)


class BalanceResult(BaseModel):
    """Normalized wallet or merchant account balance."""

    model_config = ConfigDict(extra="ignore")

    provider: str
    available_balance: str
    currency: str
    raw: dict[str, Any] = Field(default_factory=dict)
