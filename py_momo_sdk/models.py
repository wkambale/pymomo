from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from py_momo_sdk.utils import (
    _CONTROL_CHAR_RE,
    validate_amount,
    validate_currency,
    validate_header_value,
    validate_reference_id,
)

_MAX_NOTE_LENGTH = 160


def _validate_external_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("external_id must be a non-empty string")
    return validate_header_value(value, field_name="external_id")


def _validate_note_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"{field_name} must not contain control characters")
    if len(value) > _MAX_NOTE_LENGTH:
        raise ValueError(f"{field_name} must not exceed {_MAX_NOTE_LENGTH} characters")
    return value


def _validate_positive_expires_in(value: object) -> object:
    if type(value) in (bool, float):
        raise ValueError("expires_in must be a positive integer")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped.isascii() or not stripped.isdigit():
            raise ValueError("expires_in must be a positive integer")
    if isinstance(value, int) and value <= 0:
        raise ValueError("expires_in must be a positive integer")
    return value


def _validate_optional_non_negative_int(value: object, *, field_name: str) -> object:
    if value is None:
        return None
    if type(value) in (bool, float):
        raise ValueError(f"{field_name} must be a non-negative integer")
    if isinstance(value, int) and value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


class TransactionStatus(str, Enum):
    pending = "PENDING"
    successful = "SUCCESSFUL"
    failed = "FAILED"


class AccountHolderIdType(str, Enum):
    msisdn = "msisdn"
    email = "email"
    party_code = "party_code"


# --- Request models ---


class Party(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    party_id_type: str = Field(alias="partyIdType")
    party_id: str = Field(alias="partyId")

    @field_validator("party_id_type")
    @classmethod
    def _check_party_id_type(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("party_id_type must be a non-empty string")
        return validate_header_value(value.strip(), field_name="party_id_type")

    @field_validator("party_id")
    @classmethod
    def _check_party_id(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("party_id must be a non-empty string")
        return validate_header_value(value.strip(), field_name="party_id")


class _BaseTransactionRequest(BaseModel):
    """Shared request fields and validators for MTN MoMo transaction writes."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    currency: str
    external_id: str = Field(alias="externalId")
    payer_message: str = Field(default="", alias="payerMessage")
    payee_note: str = Field(default="", alias="payeeNote")

    @field_validator("amount")
    @classmethod
    def _check_amount(cls, value: str) -> str:
        return validate_amount(value)

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, value: str) -> str:
        return validate_currency(value)

    @field_validator("external_id")
    @classmethod
    def _check_external_id(cls, value: str) -> str:
        return _validate_external_id(value)

    @field_validator("payer_message")
    @classmethod
    def _check_payer_message(cls, value: str) -> str:
        return _validate_note_text(value, field_name="payer_message")

    @field_validator("payee_note")
    @classmethod
    def _check_payee_note(cls, value: str) -> str:
        return _validate_note_text(value, field_name="payee_note")

    @model_validator(mode="after")
    def _check_currency_precision(self) -> _BaseTransactionRequest:
        validate_amount(self.amount, currency=self.currency)
        return self


class RequestToPayRequest(_BaseTransactionRequest):
    payer: Party


class TransferRequest(_BaseTransactionRequest):
    payee: Party


class DepositRequest(_BaseTransactionRequest):
    payee: Party


class RefundRequest(_BaseTransactionRequest):
    reference_id_to_refund: str = Field(alias="referenceIdToRefund")

    @field_validator("reference_id_to_refund")
    @classmethod
    def _check_reference_id_to_refund(cls, value: str) -> str:
        validate_reference_id(value)
        return value


class RequestToWithdrawRequest(_BaseTransactionRequest):
    payer: Party


class BcAuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    scope: str = "profile"
    access_type: str = Field(default="offline", alias="access_type")
    login_hint: str = Field(alias="login_hint")


class PreApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    payer: Party
    payer_currency: str = Field(alias="payerCurrency")
    payer_message: str = Field(default="", alias="payerMessage")
    validity_time: int = Field(alias="validityTime", gt=0)

    @field_validator("payer_currency")
    @classmethod
    def _check_payer_currency(cls, value: str) -> str:
        return validate_currency(value)

    @field_validator("payer_message")
    @classmethod
    def _check_payer_message(cls, value: str) -> str:
        return _validate_note_text(value, field_name="payer_message")

    @field_validator("validity_time", mode="before")
    @classmethod
    def _check_validity_time(cls, value: object) -> object:
        if type(value) in (bool, float):
            raise ValueError("validity_time must be a positive integer")
        if isinstance(value, int) and value <= 0:
            raise ValueError("validity_time must be a positive integer")
        return value


class PreApprovalResult(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    payer: Party | None = None
    payer_currency: str | None = Field(default=None, alias="payerCurrency")
    payer_message: str | None = Field(default=None, alias="payerMessage")
    validity_time: int | None = Field(default=None, alias="validityTime")
    status: str
    reason: str | None = None
    reason_code: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_error_reason(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("reason"), dict):
            reason_obj = data["reason"]
            code = reason_obj.get("code")
            msg = reason_obj.get("message")
            code_str = code.strip() if isinstance(code, str) and code.strip() else None
            msg_str = msg.strip() if isinstance(msg, str) and msg.strip() else None
            updated = dict(data)
            if code_str and msg_str:
                updated["reason"] = f"{code_str}: {msg_str}"
            elif code_str or msg_str:
                updated["reason"] = code_str or msg_str
            else:
                updated["reason"] = None
            if code_str and "reason_code" not in updated:
                updated["reason_code"] = code_str
            return updated
        return data

    def is_approved(self) -> bool:
        return self.status.upper() in {"APPROVED", "SUCCESSFUL"}

    def is_pending(self) -> bool:
        return self.status.upper() == "PENDING"

    def is_failed(self) -> bool:
        return self.status.upper() in {"FAILED", "REJECTED", "EXPIRED", "CANCELLED"}


# --- Response models ---


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    access_token: str
    token_type: str
    expires_in: int = Field(gt=0)

    @field_validator("access_token")
    @classmethod
    def _check_access_token(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("access_token must not be empty")
        return validate_header_value(
            value, field_name="access_token", allow_whitespace=False
        )

    @field_validator("expires_in", mode="before")
    @classmethod
    def _check_expires_in(cls, value: object) -> object:
        return _validate_positive_expires_in(value)

    def __repr__(self) -> str:
        return (
            f"TokenResponse(access_token=<redacted>, "
            f"token_type={self.token_type!r}, expires_in={self.expires_in!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class OAuth2TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    access_token: str
    token_type: str
    expires_in: int = Field(gt=0)
    scope: str | None = None
    refresh_token: str | None = None
    refresh_token_expired_in: int | None = None

    @field_validator("access_token")
    @classmethod
    def _check_access_token(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("access_token must not be empty")
        return validate_header_value(
            value, field_name="access_token", allow_whitespace=False
        )

    @field_validator("refresh_token")
    @classmethod
    def _check_refresh_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("refresh_token must not be empty")
        return validate_header_value(
            value, field_name="refresh_token", allow_whitespace=False
        )

    @field_validator("expires_in", mode="before")
    @classmethod
    def _check_expires_in(cls, value: object) -> object:
        return _validate_positive_expires_in(value)

    @field_validator("refresh_token_expired_in", mode="before")
    @classmethod
    def _check_refresh_token_expired_in(cls, value: object) -> object:
        return _validate_optional_non_negative_int(
            value, field_name="refresh_token_expired_in"
        )

    def __repr__(self) -> str:
        refresh_repr = "<redacted>" if self.refresh_token is not None else "None"
        return (
            f"OAuth2TokenResponse(access_token=<redacted>, "
            f"token_type={self.token_type!r}, expires_in={self.expires_in!r}, "
            f"scope={self.scope!r}, refresh_token={refresh_repr})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class BcAuthorizeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    auth_req_id: str = Field(alias="auth_req_id")
    expires_in: int = Field(gt=0, alias="expires_in")
    interval: int | None = Field(default=None, alias="interval")

    @field_validator("auth_req_id")
    @classmethod
    def _check_auth_req_id(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("auth_req_id must not be empty")
        return validate_header_value(
            value, field_name="auth_req_id", allow_whitespace=False
        )

    @field_validator("expires_in", mode="before")
    @classmethod
    def _check_expires_in(cls, value: object) -> object:
        return _validate_positive_expires_in(value)

    @field_validator("interval", mode="before")
    @classmethod
    def _check_interval(cls, value: object) -> object:
        return _validate_optional_non_negative_int(value, field_name="interval")

    def __repr__(self) -> str:
        return (
            f"BcAuthorizeResponse(auth_req_id=<redacted>, "
            f"expires_in={self.expires_in!r}, interval={self.interval!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class Balance(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    available_balance: str = Field(alias="availableBalance")
    currency: str


class TransactionResult(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    financial_transaction_id: str | None = Field(
        default=None, alias="financialTransactionId"
    )
    external_id: str | None = Field(default=None, alias="externalId")
    amount: str | None = None
    currency: str | None = None
    payer: Party | None = None
    payee: Party | None = None
    payer_message: str | None = Field(default=None, alias="payerMessage")
    payee_note: str | None = Field(default=None, alias="payeeNote")
    status: TransactionStatus
    reason: str | None = None
    reason_code: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_error_reason(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("reason"), dict):
            reason_obj = data["reason"]
            code = reason_obj.get("code")
            msg = reason_obj.get("message")
            code_str = code.strip() if isinstance(code, str) and code.strip() else None
            msg_str = msg.strip() if isinstance(msg, str) and msg.strip() else None
            updated = dict(data)
            if code_str and msg_str:
                updated["reason"] = f"{code_str}: {msg_str}"
            elif code_str or msg_str:
                updated["reason"] = code_str or msg_str
            else:
                updated["reason"] = None
            if code_str and "reason_code" not in updated:
                updated["reason_code"] = code_str
            return updated
        return data

    def is_successful(self) -> bool:
        return self.status == TransactionStatus.successful

    def is_pending(self) -> bool:
        return self.status == TransactionStatus.pending

    def is_failed(self) -> bool:
        return self.status == TransactionStatus.failed


class BasicUserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    sub: str | None = None
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    birthdate: str | None = None
    locale: str | None = None
    gender: str | None = None
    status: str | None = None


class ApiUserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    provider_callback_host: str | None = Field(
        default=None, alias="providerCallbackHost"
    )
    target_environment: str | None = Field(default=None, alias="targetEnvironment")


class ApiKeyResult(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    api_key: str = Field(alias="apiKey")

    @field_validator("api_key")
    @classmethod
    def _check_api_key(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("api_key must not be empty")
        return validate_header_value(
            value, field_name="api_key", allow_whitespace=False
        )

    def __repr__(self) -> str:
        return "ApiKeyResult(api_key=<redacted>)"

    def __str__(self) -> str:
        return self.__repr__()
