from __future__ import annotations

from typing import TYPE_CHECKING

from py_momo_sdk.airtel.models import (
    AirtelCollectionRequest,
    AirtelSubscriber,
    AirtelTransactionRequest,
    AirtelTransactionResponse,
    check_airtel_response_status,
    normalise_airtel_msisdn,
)
from py_momo_sdk.http import parse_model
from py_momo_sdk.utils import (
    encode_path_segment,
    generate_reference_id,
    validate_airtel_reference_id,
)

if TYPE_CHECKING:
    from py_momo_sdk.airtel.client import AirtelClient


class Collection:
    """Airtel Collection product client."""

    def __init__(self, client: AirtelClient) -> None:
        self._client = client

    def request_to_pay(
        self,
        amount: str,
        payer_msisdn: str,
        reference_id: str | None = None,
        *,
        external_id: str | None = None,
    ) -> str:
        """Initiate a payment collection (USSD Push).

        Args:
            amount: The transaction amount.
            payer_msisdn: Phone number of the payer (international or local).
            reference_id: Optional client-supplied reference/transaction ID.
            external_id: Optional merchant reference sent in Airtel's ``reference`` field.

        Returns:
            The reference ID associated with the transaction.
        """
        ref = reference_id or generate_reference_id()
        validate_airtel_reference_id(ref)
        merchant_ref = external_id or ref

        payload = AirtelCollectionRequest(
            reference=merchant_ref,
            subscriber=AirtelSubscriber(
                country=self._client._config.country,
                currency=self._client._config.currency,
                msisdn=normalise_airtel_msisdn(
                    payer_msisdn, self._client._config.country
                ),
            ),
            transaction=AirtelTransactionRequest(
                amount=amount,
                country=self._client._config.country,
                currency=self._client._config.currency,
                id=ref,
            ),
        )

        response = self._client.request(
            "POST",
            "/merchant/v1/payments/",
            json=payload.model_dump(by_alias=True, mode="json", exclude_none=True),
        )
        if response.content:
            try:
                parsed = response.json()
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                check_airtel_response_status(parsed, reference_id=ref)
        return ref

    def get_payment_status(self, reference_id: str) -> AirtelTransactionResponse:
        """Query the status of a payment collection.

        Args:
            reference_id: The transaction reference/ID.

        Returns:
            An AirtelTransactionResponse object.
        """
        validate_airtel_reference_id(reference_id)
        encoded = encode_path_segment(reference_id, field_name="reference_id")
        response = self._client.request(
            "GET",
            f"/standard/v1/payments/{encoded}",
        )
        return parse_model(response, AirtelTransactionResponse)
