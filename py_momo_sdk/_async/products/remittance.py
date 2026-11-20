from __future__ import annotations

from py_momo_sdk._async.products.base import AsyncBaseProduct
from py_momo_sdk.http import parse_model
from py_momo_sdk.models import Party, TransactionResult, TransferRequest
from py_momo_sdk.utils import (
    generate_reference_id,
    normalise_msisdn,
    validate_reference_id,
)


class Remittance(AsyncBaseProduct):
    """Asynchronous Remittance product client."""

    _product_name = "remittance"
    _token_path = "/remittance/token/"  # nosec B105

    async def transfer(
        self,
        amount: str,
        currency: str,
        payee_msisdn: str,
        external_id: str,
        *,
        payer_message: str = "",
        payee_note: str = "",
        reference_id: str | None = None,
    ) -> str:
        """Transfer funds to a payee.

        Args:
            amount: The transaction amount.
            currency: The transaction currency.
            payee_msisdn: The MSISDN of the payee.
            external_id: The external ID.
            payer_message: Message to the payer.
            payee_note: Note to the payee.
            reference_id: Optional client-supplied reference ID.

        Returns:
            The reference ID associated with the transfer.
        """
        if reference_id is not None:
            validate_reference_id(reference_id)
        ref = reference_id or generate_reference_id()

        payload = TransferRequest(
            amount=amount,
            currency=currency,
            externalId=external_id,
            payee=Party(
                partyIdType="MSISDN",
                partyId=normalise_msisdn(payee_msisdn),
            ),
            payerMessage=payer_message,
            payeeNote=payee_note,
        )

        await self._http.request(
            "POST",
            "/remittance/v1_0/transfer",
            headers=await self._build_headers(reference_id=ref, include_callback=True),
            json=payload.model_dump(by_alias=True, mode="json"),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return ref

    async def get_transfer_status(self, reference_id: str) -> TransactionResult:
        """Poll the status of a transfer transaction.

        Args:
            reference_id: The transaction reference ID.

        Returns:
            A TransactionResult object detailing the status of the transaction.
        """
        validate_reference_id(reference_id)
        response = await self._http.request(
            "GET",
            f"/remittance/v1_0/transfer/{reference_id}",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, TransactionResult)
