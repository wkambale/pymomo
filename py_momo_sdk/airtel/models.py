from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from py_momo_sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    PyMomoSDKError,
    ResourceNotFoundError,
    TransactionFailedError,
)
from py_momo_sdk.utils import (
    normalise_msisdn,
    validate_amount,
    validate_country_code,
    validate_currency,
)

_AIRTEL_COUNTRY_CALLING_CODES: dict[str, str] = {
    "CD": "243",
    "CG": "242",
    "GA": "241",
    "GH": "233",
    "KE": "254",
    "MG": "261",
    "MW": "265",
    "NE": "227",
    "NG": "234",
    "RW": "250",
    "SC": "248",
    "TD": "235",
    "TZ": "255",
    "UG": "256",
    "ZM": "260",
}

_AIRTEL_TERMINAL_FAILURE_STATUSES = frozenset(
    {"TF", "FAILED", "FAIL", "REJECTED", "CANCELLED", "CANCELED", "EXPIRED"}
)


def normalise_airtel_msisdn(msisdn: str, country: str) -> str:
    """Normalise an MSISDN to Airtel Africa's local subscriber format.

    Strips formatting characters, leading ``00``, the matching country calling
    code for ``country`` (e.g. ``256`` for ``UG``), and any leading trunk ``0``
    so the local subscriber digits (e.g. ``701234567``) match Airtel's
    ``X-Country`` header contract.
    """
    digits = normalise_msisdn(msisdn)
    calling_code = _AIRTEL_COUNTRY_CALLING_CODES.get(country.upper())
    if (
        calling_code
        and digits.startswith(calling_code)
        and len(digits) - len(calling_code) >= 7
    ):
        digits = digits[len(calling_code) :]
    if digits.startswith("0") and len(digits) > 7:
        digits = digits.lstrip("0")
    return digits


def check_airtel_response_status(
    data: dict[str, Any], *, reference_id: str | None = None
) -> None:
    """Inspect an Airtel HTTP 200 JSON envelope and raise on business failures."""
    status_obj = data.get("status")
    status_success: bool | None = None
    status_code_str: str | None = None
    result_code_str: str | None = None
    status_msg: str | None = None
    if isinstance(status_obj, dict):
        raw_success = status_obj.get("success")
        if isinstance(raw_success, bool):
            status_success = raw_success
        raw_code = status_obj.get("code")
        if isinstance(raw_code, str) and raw_code.strip():
            status_code_str = raw_code.strip()
        raw_res_code = status_obj.get("result_code")
        if isinstance(raw_res_code, str) and raw_res_code.strip():
            result_code_str = raw_res_code.strip()
        raw_msg = status_obj.get("message")
        if isinstance(raw_msg, str) and raw_msg.strip():
            status_msg = raw_msg.strip()

    tx_status: str | None = None
    tx_msg: str | None = None
    data_obj = data.get("data")
    if isinstance(data_obj, dict):
        tx_obj = data_obj.get("transaction")
        if isinstance(tx_obj, dict):
            raw_tx_status = tx_obj.get("status")
            if isinstance(raw_tx_status, str) and raw_tx_status.strip():
                tx_status = raw_tx_status.strip().upper()
            raw_tx_msg = tx_obj.get("message")
            if isinstance(raw_tx_msg, str) and raw_tx_msg.strip():
                tx_msg = raw_tx_msg.strip()

    error_code = result_code_str or status_code_str
    base_reason = tx_msg or status_msg
    if error_code and base_reason and error_code not in base_reason:
        reason = f"{error_code}: {base_reason}"
    else:
        reason = base_reason or error_code or "Airtel transaction rejected"

    if status_success is False:
        if reference_id is not None and tx_status in _AIRTEL_TERMINAL_FAILURE_STATUSES:
            raise TransactionFailedError(
                reference_id=reference_id,
                reason=reason,
                status_code=200,
                error_code=error_code,
                response_body=data,
                provider="Airtel Money",
            )
        if status_code_str == "400":
            raise BadRequestError(
                reason,
                response_body=data,
                reference_id=reference_id,
                status_code=200,
                error_code=error_code,
                reason=reason,
                provider="Airtel Money",
            )
        if status_code_str in ("401", "403"):
            raise AuthenticationError(
                reason,
                reference_id=reference_id,
                status_code=200,
                error_code=error_code,
                reason=reason,
                response_body=data,
                provider="Airtel Money",
            )
        if status_code_str == "404":
            raise ResourceNotFoundError(
                reason,
                reference_id=reference_id,
                status_code=200,
                error_code=error_code,
                reason=reason,
                response_body=data,
                provider="Airtel Money",
            )
        raise PyMomoSDKError(
            reason,
            reference_id=reference_id,
            status_code=200,
            error_code=error_code,
            reason=reason,
            response_body=data,
            provider="Airtel Money",
        )
    if reference_id is not None and tx_status in _AIRTEL_TERMINAL_FAILURE_STATUSES:
        raise TransactionFailedError(
            reference_id=reference_id,
            reason=reason,
            status_code=200,
            error_code=error_code,
            response_body=data,
            provider="Airtel Money",
        )


def check_airtel_status_query_response(
    data: dict[str, Any], *, reference_id: str
) -> None:
    """Raise a structured Airtel error when a GET status response omits ``data.transaction``."""
    data_obj = data.get("data")
    if isinstance(data_obj, dict) and isinstance(data_obj.get("transaction"), dict):
        return
    status_obj = data.get("status")
    if not isinstance(status_obj, dict):
        return
    raw_success = status_obj.get("success")
    raw_code = status_obj.get("code")
    code_str = (
        raw_code.strip() if isinstance(raw_code, str) and raw_code.strip() else None
    )
    if raw_success is False or (code_str is not None and code_str != "200"):
        check_airtel_response_status(
            {
                **data,
                "status": {**status_obj, "success": False},
            },
            reference_id=reference_id,
        )


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

    @model_validator(mode="after")
    def _check_zero_decimal_amount(self) -> AirtelTransactionRequest:
        validate_amount(self.amount, currency=self.currency)
        return self


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
    wallet_type: str | None = None
    currency: str | None = None
    country: str | None = None
    name: str | None = None


class AirtelDisbursementTransaction(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    amount: str
    id: str
    type: str | None = None
    country: str | None = None
    currency: str | None = None

    @field_validator("amount")
    @classmethod
    def _check_amount(cls, value: str) -> str:
        return validate_amount(value)

    @model_validator(mode="after")
    def _check_zero_decimal_amount(self) -> AirtelDisbursementTransaction:
        if self.currency is not None:
            validate_amount(self.amount, currency=self.currency)
        return self


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
    result_code: str | None = Field(default=None, alias="result_code")
    success: bool | None = None


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
        if self.status.success is False:
            return False
        tx_status = self._normalized_tx_status()
        if tx_status is None:
            return False
        return tx_status in _AIRTEL_SUCCESS_STATUSES

    def is_pending(self) -> bool:
        """Verify if the transaction status is currently pending."""
        if self.status.success is False:
            return False
        tx_status = self._normalized_tx_status()
        if tx_status is not None:
            return tx_status in _AIRTEL_PENDING_STATUSES
        return self.status.result_code in ("00", "02", "DP0000000000", None)

    def is_failed(self) -> bool:
        """Verify if the transaction status is failed."""
        if self.status.success is False:
            return True
        tx_status = self._normalized_tx_status()
        if tx_status is not None:
            return (
                tx_status not in _AIRTEL_SUCCESS_STATUSES
                and tx_status not in _AIRTEL_PENDING_STATUSES
            )
        return self.status.result_code not in ("00", "02", "DP0000000000", None)


class AirtelWalletDetails(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    msisdn: str = ""
    balance: str
    currency: str
    status: str = ""
    account_status: str | None = None
    account_type: str | None = None


class AirtelWalletData(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    wallet: AirtelWalletDetails

    @model_validator(mode="before")
    @classmethod
    def _normalize_flat_balance(cls, data: Any) -> Any:
        if isinstance(data, dict) and "wallet" not in data and "balance" in data:
            return {
                "wallet": {
                    "msisdn": str(data.get("msisdn") or ""),
                    "balance": str(data["balance"]),
                    "currency": str(data.get("currency") or ""),
                    "status": str(
                        data.get("account_status") or data.get("status") or ""
                    ),
                    "account_status": data.get("account_status"),
                    "account_type": data.get("account_type"),
                }
            }
        return data


class AirtelBalanceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    data: AirtelWalletData
    status: AirtelStatus | None = None

    @property
    def balance(self) -> str:
        return self.data.wallet.balance

    @property
    def currency(self) -> str:
        return self.data.wallet.currency

    @property
    def account_status(self) -> str | None:
        return self.data.wallet.account_status or self.data.wallet.status or None

    @property
    def account_type(self) -> str | None:
        return self.data.wallet.account_type


class AirtelUserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    first_name: str | None = None
    last_name: str | None = None
    msisdn: str | None = None
    grade: str | None = None
    is_barred: bool | None = None
    is_pin_set: bool | None = None
    registration: dict[str, Any] | None = None


class AirtelUserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    data: AirtelUserInfo
    status: AirtelStatus | None = None
