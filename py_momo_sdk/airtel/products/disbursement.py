from __future__ import annotations

from typing import TYPE_CHECKING

from py_momo_sdk.airtel.models import (
    AirtelBalanceResponse,
    AirtelDisbursementRequest,
    AirtelTransactionResponse,
)
from py_momo_sdk.http import parse_model
from py_momo_sdk.utils import (
    generate_reference_id,
    normalise_msisdn,
    validate_reference_id,
)

if TYPE_CHECKING:
    from py_momo_sdk.airtel.client import AirtelClient


class Disbursement:
    """Airtel Disbursement product client."""

    def __init__(self, client: AirtelClient) -> None:
        self._client = client

    def transfer(
        self,
        amount: str,
        payee_msisdn: str,
        reference_id: str | None = None,
    ) -> str:
        """Initiate a disbursement (Payout) to a subscriber.

        Args:
            amount: The transaction amount.
            payee_msisdn: Phone number of the payee.
            reference_id: Optional client-supplied reference/transaction ID.

        Returns:
            The reference ID associated with the transaction.
        """
        if not self._client._config.pin:
            raise ValueError("pin is required for Airtel disbursements")

        ref = reference_id or generate_reference_id()
        validate_reference_id(ref)

        payload = AirtelDisbursementRequest(
            amount=amount,
            number=normalise_msisdn(payee_msisdn),
            reference=ref,
            pin=self._client._config.pin,
        )

        self._client.request(
            "POST",
            "/standard/v1/disbursements/",
            json=payload.model_dump(by_alias=True, mode="json"),
        )
        return ref

    def get_transfer_status(self, reference_id: str) -> AirtelTransactionResponse:
        """Query the status of a disbursement transaction.

        Args:
            reference_id: The transaction reference ID.

        Returns:
            An AirtelTransactionResponse object.
        """
        validate_reference_id(reference_id)
        response = self._client.request(
            "GET",
            f"/standard/v1/disbursements/{reference_id}",
        )
        return parse_model(response, AirtelTransactionResponse)

    def get_balance(self) -> AirtelBalanceResponse:
        """Query the merchant wallet balance.

        Returns:
            An AirtelBalanceResponse object.
        """
        response = self._client.request(
            "GET",
            "/merchant/v2/wallets/balance/",
        )
        return parse_model(response, AirtelBalanceResponse)
