from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from py_momo_sdk.utils import validate_amount, validate_country_code, validate_currency

# --- Request models ---


class AirtelSubscriber(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    country: str
    currency: str
    msisdn: str

    @field_validator("country")
    @classmethod
    def _check_country(cls, value: str) -> str:
        return validate_country_code(value)

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, value: str) -> str:
        return validate_currency(value)


class AirtelTransactionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    country: str
    currency: str
    id: str

    @field_validator("amount")
    @classmethod
    def _check_amount(cls, value: str) -> str:
        return validate_amount(value)

    @field_validator("country")
    @classmethod
    def _check_country(cls, value: str) -> str:
        return validate_country_code(value)

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, value: str) -> str:
        return validate_currency(value)


class AirtelCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    reference: str
    subscriber: AirtelSubscriber
    transaction: AirtelTransactionRequest


_AIRTEL_SUCCESS_STATUSES = frozenset({"TS", "SUCCESS", "SUCCESSFUL"})
_AIRTEL_PENDING_STATUSES = frozenset(
    {"TIP", "PENDING", "INITIATED", "02", "AMBIGUOUS", "TA"}
)


class AirtelDisbursementPayee(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    msisdn: str


class AirtelDisbursementTransaction(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    id: str

    @field_validator("amount")
    @classmethod
    def _check_amount(cls, value: str) -> str:
        return validate_amount(value)


class AirtelDisbursementRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    payee: AirtelDisbursementPayee
    reference: str
    pin: str
    transaction: AirtelDisbursementTransaction

    def __repr__(self) -> str:
        return (
            f"AirtelDisbursementRequest(payee={self.payee!r}, "
            f"reference={self.reference!r}, transaction={self.transaction!r}, "
            f"pin=<redacted>)"
        )

    def __str__(self) -> str:
        return self.__repr__()


# --- Response models ---


class AirtelStatus(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    code: str
    message: str
    result_code: str = Field(alias="result_code")


class AirtelTransactionDetails(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    airtel_money_id: str | None = Field(default=None, alias="airtel_money_id")
    id: str | None = None
    status: str | None = None
    message: str | None = None
    amount: str | None = None
    currency: str | None = None
    reference: str | None = None


class AirtelData(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    transaction: AirtelTransactionDetails


class AirtelTransactionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    status: AirtelStatus
    data: AirtelData

    def _normalized_tx_status(self) -> str | None:
        raw = self.data.transaction.status
        if raw is None:
            return None
        stripped = raw.strip().upper()
        return stripped or None

    def is_successful(self) -> bool:
        """Verify if the transaction has settled successfully.

        Uses ``data.transaction.status`` as the authoritative transaction state
        so that a successful API query envelope (for example ``result_code == "00"``)
        cannot falsely mark a pending, initiated, or failed transaction as
        successful.
        """
        tx_status = self._normalized_tx_status()
        if tx_status is None:
            return False
        return tx_status in _AIRTEL_SUCCESS_STATUSES

    def is_pending(self) -> bool:
        """Verify if the transaction status is currently pending."""
        tx_status = self._normalized_tx_status()
        if tx_status is not None:
            return tx_status in _AIRTEL_PENDING_STATUSES
        return self.status.result_code == "02"

    def is_failed(self) -> bool:
        """Verify if the transaction status is failed."""
        tx_status = self._normalized_tx_status()
        if tx_status is not None:
            return (
                tx_status not in _AIRTEL_SUCCESS_STATUSES
                and tx_status not in _AIRTEL_PENDING_STATUSES
            )
        return self.status.result_code not in ("00", "02", "DP0000000000")


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
