from __future__ import annotations

from typing import TYPE_CHECKING

from py_momo_sdk.airtel.models import (
    AirtelCollectionRequest,
    AirtelSubscriber,
    AirtelTransactionRequest,
    AirtelTransactionResponse,
)
from py_momo_sdk.http import parse_model
from py_momo_sdk.utils import (
    generate_reference_id,
    normalise_msisdn,
    validate_reference_id,
)

if TYPE_CHECKING:
    from py_momo_sdk._async.airtel.client import AsyncAirtelClient


class AsyncAirtelCollection:
    """Asynchronous Airtel Collection product client."""

    def __init__(self, client: AsyncAirtelClient) -> None:
        self._client = client

    async def request_to_pay(
        self,
        amount: str,
        payer_msisdn: str,
        reference_id: str | None = None,
    ) -> str:
        """Initiate a payment collection (USSD Push) asynchronously."""
        ref = reference_id or generate_reference_id()
        validate_reference_id(ref)

        payload = AirtelCollectionRequest(
            reference=ref,
            subscriber=AirtelSubscriber(
                country=self._client._config.country,
                currency=self._client._config.currency,
                msisdn=normalise_msisdn(payer_msisdn),
            ),
            transaction=AirtelTransactionRequest(
                amount=amount,
                country=self._client._config.country,
                currency=self._client._config.currency,
                id=ref,
            ),
        )

        await self._client.request(
            "POST",
            "/merchant/v1/payments/",
            json=payload.model_dump(by_alias=True, mode="json"),
        )
        return ref

    async def get_payment_status(self, reference_id: str) -> AirtelTransactionResponse:
        """Query the status of a payment collection asynchronously."""
        validate_reference_id(reference_id)
        response = await self._client.request(
            "GET",
            f"/standard/v1/payments/{reference_id}",
        )
        return parse_model(response, AirtelTransactionResponse)
