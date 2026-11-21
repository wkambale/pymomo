from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from py_momo_sdk.utils import validate_amount, validate_currency, validate_header_value


def _validate_external_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("external_id must be a non-empty string")
    return validate_header_value(value, field_name="external_id")


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


class RequestToPayRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    currency: str
    external_id: str = Field(alias="externalId")
    payer: Party
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


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    currency: str
    external_id: str = Field(alias="externalId")
    payee: Party
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


class DepositRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    currency: str
    external_id: str = Field(alias="externalId")
    payee: Party
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


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    currency: str
    external_id: str = Field(alias="externalId")
    reference_id_to_refund: str = Field(alias="referenceIdToRefund")
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


class RequestToWithdrawRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    currency: str
    external_id: str = Field(alias="externalId")
    payer: Party
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


class BcAuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    scope: str = "profile"
    access_type: str = Field(default="offline", alias="access_type")
    login_hint: str = Field(alias="login_hint")


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
        return validate_header_value(value, field_name="access_token")

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
        return validate_header_value(value, field_name="access_token")

    @field_validator("refresh_token")
    @classmethod
    def _check_refresh_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("refresh_token must not be empty")
        return validate_header_value(value, field_name="refresh_token")

    @field_validator("expires_in", mode="before")
    @classmethod
    def _check_expires_in(cls, value: object) -> object:
        return _validate_positive_expires_in(value)

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

    @field_validator("expires_in", mode="before")
    @classmethod
    def _check_expires_in(cls, value: object) -> object:
        return _validate_positive_expires_in(value)


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
        return validate_header_value(value, field_name="api_key")

    def __repr__(self) -> str:
        return "ApiKeyResult(api_key=<redacted>)"

    def __str__(self) -> str:
        return self.__repr__()
