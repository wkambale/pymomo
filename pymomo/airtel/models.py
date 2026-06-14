from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# --- Request models ---


class AirtelSubscriber(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    country: str
    currency: str
    msisdn: str


class AirtelTransactionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    country: str
    currency: str
    id: str


class AirtelCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    reference: str
    subscriber: AirtelSubscriber
    transaction: AirtelTransactionRequest


class AirtelDisbursementRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    number: str
    reference: str
    pin: str


# --- Response models ---


class AirtelStatus(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    code: str
    message: str
    result_code: str = Field(alias="result_code")


class AirtelTransactionDetails(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    airtel_money_id: Optional[str] = Field(default=None, alias="airtel_money_id")
    id: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None
    amount: Optional[str] = None
    currency: Optional[str] = None
    reference: Optional[str] = None


class AirtelData(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    transaction: AirtelTransactionDetails


class AirtelTransactionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    status: AirtelStatus
    data: AirtelData

    def is_successful(self) -> bool:
        """Verify if transaction request succeeded or initiated successfully."""
        return self.status.result_code in ("00", "DP0000000000") or (
            self.data.transaction.status in ("SUCCESS", "SUCCESSFUL", "Initiated", "AS")
        )

    def is_pending(self) -> bool:
        """Verify if transaction status is currently pending."""
        return self.status.result_code == "02" or (
            self.data.transaction.status in ("PENDING", "Pending", "02")
        )

    def is_failed(self) -> bool:
        """Verify if transaction status is failed."""
        return self.status.result_code not in ("00", "02", "DP0000000000") and (
            self.data.transaction.status not in ("SUCCESS", "SUCCESSFUL", "Initiated", "AS", "PENDING", "Pending", "02")
        )


class AirtelWalletDetails(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    msisdn: str
    balance: str
    currency: str
    status: str


class AirtelWalletData(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    wallet: AirtelWalletDetails


class AirtelBalanceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    data: AirtelWalletData
