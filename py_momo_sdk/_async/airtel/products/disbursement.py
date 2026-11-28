from __future__ import annotations

from typing import TYPE_CHECKING

from py_momo_sdk.airtel.models import (
    AirtelBalanceResponse,
    AirtelDisbursementPayee,
    AirtelDisbursementRequest,
    AirtelDisbursementTransaction,
    AirtelTransactionResponse,
    check_airtel_response_status,
    check_airtel_status_query_response,
    normalise_airtel_msisdn,
)
from py_momo_sdk.http import parse_model
from py_momo_sdk.utils import (
    encode_path_segment,
    generate_reference_id,
    validate_airtel_reference_id,
    validate_amount,
)

if TYPE_CHECKING:
    from py_momo_sdk._async.airtel.client import AsyncAirtelClient


class AsyncAirtelDisbursement:
    """Asynchronous Airtel Disbursement product client."""

    def __init__(self, client: AsyncAirtelClient) -> None:
        self._client = client

    async def transfer(
        self,
        amount: str,
        payee_msisdn: str,
        reference_id: str | None = None,
        *,
        external_id: str | None = None,
        transaction_type: str | None = None,
        wallet_type: str | None = None,
    ) -> str:
        """Initiate a disbursement (payout) to a subscriber asynchronously."""
        if not self._client._config.pin:
            raise ValueError("pin is required for Airtel disbursements")

        validate_amount(amount, currency=self._client._config.currency)
        ref = reference_id or generate_reference_id()
        validate_airtel_reference_id(ref)
        merchant_ref = external_id or ref

        payload = AirtelDisbursementRequest(
            payee=AirtelDisbursementPayee(
                msisdn=normalise_airtel_msisdn(
                    payee_msisdn, self._client._config.country
                ),
                wallet_type=wallet_type,
            ),
            reference=merchant_ref,
            pin=self._client._config.pin,
            transaction=AirtelDisbursementTransaction(
                amount=amount,
                id=ref,
                type=transaction_type,
                country=self._client._config.country,
                currency=self._client._config.currency,
            ),
        )

        response = await self._client.request(
            "POST",
            "/standard/v1/disbursements/",
            json=payload.model_dump(by_alias=True, mode="json", exclude_none=True),
            reference_id=ref,
        )
        if response.content:
            try:
                parsed = response.json()
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                check_airtel_response_status(parsed, reference_id=ref)
        return ref

    async def get_transfer_status(self, reference_id: str) -> AirtelTransactionResponse:
        """Query the status of a disbursement transaction asynchronously."""
        validate_airtel_reference_id(reference_id)
        encoded = encode_path_segment(reference_id, field_name="reference_id")
        response = await self._client.request(
            "GET",
            f"/standard/v1/disbursements/{encoded}",
            reference_id=reference_id,
        )
        if response.content:
            try:
                parsed = response.json()
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                check_airtel_status_query_response(parsed, reference_id=reference_id)
        return parse_model(
            response, AirtelTransactionResponse, reference_id=reference_id
        )

    async def get_balance(self) -> AirtelBalanceResponse:
        """Query the merchant wallet balance asynchronously."""
        response = await self._client.request(
            "GET",
            "/standard/v1/users/balance",
        )
        if response.content:
            try:
                parsed = response.json()
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                check_airtel_response_status(parsed)
        return parse_model(response, AirtelBalanceResponse)
