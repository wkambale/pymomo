from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from py_momo_sdk.utils import (
    validate_amount,
    validate_callback_url,
    validate_currency,
    validate_header_value,
)


def validate_email_address(email: str) -> str:
    """Validate that an email address is non-empty, header-safe, and well-formed."""
    if not isinstance(email, str) or not email.strip():
        raise ValueError("email must be a non-empty string")
    cleaned = email.strip()
    validate_header_value(cleaned, field_name="email")
    if (
        any(ch.isspace() for ch in cleaned)
        or cleaned.count("@") != 1
        or cleaned.startswith("@")
        or cleaned.endswith("@")
    ):
        raise ValueError("email must be a valid email address")
    domain = cleaned.split("@", 1)[1]
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("email must be a valid email address")
    return cleaned


def validate_operation_kind(kind: str) -> str:
    """Validate that a status or balance operation kind is supported."""
    if kind not in ("collection", "disbursement"):
        raise ValueError("kind must be 'collection' or 'disbursement'")
    return kind


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

    @field_validator("currencies")
    @classmethod
    def _normalize_currencies(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("Currency codes in capabilities must be non-empty")
            normalized.append(item.strip().upper())
        return tuple(normalized)


class PaymentRequest(BaseModel):
    """Normalized collection payment request."""

    model_config = ConfigDict(extra="ignore")

    amount: str
    currency: str
    payer_msisdn: str
    payer_email: str | None = None
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

    @field_validator("payer_msisdn")
    @classmethod
    def _check_payer_msisdn(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("payer_msisdn must not be blank")
        return validate_header_value(value.strip(), field_name="payer_msisdn")

    @field_validator("payer_email")
    @classmethod
    def _check_payer_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_email_address(value)

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
    payee_bank_code: str | None = None
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

    @field_validator("payee_msisdn")
    @classmethod
    def _check_payee_msisdn(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("payee_msisdn must not be blank")
        return validate_header_value(value.strip(), field_name="payee_msisdn")

    @field_validator("payee_bank_code")
    @classmethod
    def _check_payee_bank_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("payee_bank_code must not be blank")
        return validate_header_value(value.strip(), field_name="payee_bank_code")

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
