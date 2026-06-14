from __future__ import annotations

from enum import Enum
from typing import Optional

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
    interval: Optional[int] = Field(default=None, alias="interval")


class Balance(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    available_balance: str = Field(alias="availableBalance")
    currency: str


class TransactionResult(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    financial_transaction_id: Optional[str] = Field(
        default=None, alias="financialTransactionId"
    )
    external_id: Optional[str] = Field(default=None, alias="externalId")
    amount: Optional[str] = None
    currency: Optional[str] = None
    payer: Optional[Party] = None
    payee: Optional[Party] = None
    payer_message: Optional[str] = Field(default=None, alias="payerMessage")
    payee_note: Optional[str] = Field(default=None, alias="payeeNote")
    status: TransactionStatus
    reason: Optional[str] = None

    def is_successful(self) -> bool:
        return self.status == TransactionStatus.successful

    def is_pending(self) -> bool:
        return self.status == TransactionStatus.pending

    def is_failed(self) -> bool:
        return self.status == TransactionStatus.failed


class BasicUserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    sub: Optional[str] = None
    name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    birthdate: Optional[str] = None
    locale: Optional[str] = None
    gender: Optional[str] = None
    status: Optional[str] = None


class ApiUserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    provider_callback_host: Optional[str] = Field(
        default=None, alias="providerCallbackHost"
    )
    target_environment: Optional[str] = Field(default=None, alias="targetEnvironment")


class ApiKeyResult(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    api_key: str = Field(alias="apiKey")
