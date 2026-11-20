from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


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


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    currency: str
    external_id: str = Field(alias="externalId")
    payee: Party
    payer_message: str = Field(default="", alias="payerMessage")
    payee_note: str = Field(default="", alias="payeeNote")


class DepositRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    currency: str
    external_id: str = Field(alias="externalId")
    payee: Party
    payer_message: str = Field(default="", alias="payerMessage")
    payee_note: str = Field(default="", alias="payeeNote")


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    currency: str
    external_id: str = Field(alias="externalId")
    reference_id_to_refund: str = Field(alias="referenceIdToRefund")
    payer_message: str = Field(default="", alias="payerMessage")
    payee_note: str = Field(default="", alias="payeeNote")


class RequestToWithdrawRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    currency: str
    external_id: str = Field(alias="externalId")
    payer: Party
    payer_message: str = Field(default="", alias="payerMessage")
    payee_note: str = Field(default="", alias="payeeNote")


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
    expires_in: int


class BcAuthorizeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    auth_req_id: str = Field(alias="auth_req_id")
    expires_in: int = Field(alias="expires_in")
    interval: int | None = Field(default=None, alias="interval")


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
