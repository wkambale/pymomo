from __future__ import annotations

from py_momo_sdk._async.products.base import AsyncBaseProduct
from py_momo_sdk.http import parse_model
from py_momo_sdk.models import (
    DepositRequest,
    Party,
    RefundRequest,
    TransactionResult,
    TransferRequest,
)
from py_momo_sdk.utils import (
    generate_reference_id,
    normalise_msisdn,
    validate_reference_id,
)


class Disbursement(AsyncBaseProduct):
    """Asynchronous Disbursement product client."""

    _product_name = "disbursement"
    _token_path = "/disbursement/token/"  # nosec B105

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
        callback_url: str | None = None,
        party_id_type: str = "MSISDN",
    ) -> str:
        """Transfer funds to a payee.

        Args:
            amount: The transaction amount.
            currency: The transaction currency.
            payee_msisdn: The MSISDN (or party identifier) of the payee.
            external_id: The external ID.
            payer_message: Message to the payer.
            payee_note: Note to the payee.
            reference_id: Optional client-supplied reference ID.
            callback_url: Optional per-request webhook callback URL.
            party_id_type: Party identifier type (``MSISDN``, ``EMAIL``, or ``PARTY_CODE``).

        Returns:
            The reference ID associated with the transfer.
        """
        if reference_id is not None:
            validate_reference_id(reference_id)
        ref = reference_id or generate_reference_id()
        norm_party_type = party_id_type.strip().upper()
        party_id = (
            normalise_msisdn(payee_msisdn)
            if norm_party_type == "MSISDN"
            else payee_msisdn.strip()
        )

        payload = TransferRequest(
            amount=amount,
            currency=currency,
            externalId=external_id,
            payee=Party(
                partyIdType=norm_party_type,
                partyId=party_id,
            ),
            payerMessage=payer_message,
            payeeNote=payee_note,
        )

        await self._http.request(
            "POST",
            "/disbursement/v1_0/transfer",
            headers=await self._build_headers(
                reference_id=ref,
                include_callback=True,
                callback_url=callback_url,
                include_content_type=True,
            ),
            json=payload.model_dump(by_alias=True, mode="json"),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
            idempotent=(reference_id is not None),
            reference_id=ref,
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
            f"/disbursement/v1_0/transfer/{reference_id}",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
            reference_id=reference_id,
        )
        return parse_model(response, TransactionResult, reference_id=reference_id)

    async def deposit(
        self,
        amount: str,
        currency: str,
        payee_msisdn: str,
        external_id: str,
        *,
        payer_message: str = "",
        payee_note: str = "",
        reference_id: str | None = None,
        callback_url: str | None = None,
        party_id_type: str = "MSISDN",
    ) -> str:
        """Initiate a Deposit (v2).

        Args:
            amount: The transaction amount.
            currency: The transaction currency.
            payee_msisdn: The MSISDN (or party identifier) of the payee.
            external_id: The external ID.
            payer_message: Message to the payer.
            payee_note: Note to the payee.
            reference_id: Optional client-supplied reference ID.
            callback_url: Optional per-request webhook callback URL.
            party_id_type: Party identifier type (``MSISDN``, ``EMAIL``, or ``PARTY_CODE``).

        Returns:
            The reference ID associated with the deposit.
        """
        if reference_id is not None:
            validate_reference_id(reference_id)
        ref = reference_id or generate_reference_id()
        norm_party_type = party_id_type.strip().upper()
        party_id = (
            normalise_msisdn(payee_msisdn)
            if norm_party_type == "MSISDN"
            else payee_msisdn.strip()
        )

        payload = DepositRequest(
            amount=amount,
            currency=currency,
            externalId=external_id,
            payee=Party(
                partyIdType=norm_party_type,
                partyId=party_id,
            ),
            payerMessage=payer_message,
            payeeNote=payee_note,
        )

        await self._http.request(
            "POST",
            "/disbursement/v2_0/deposit",
            headers=await self._build_headers(
                reference_id=ref,
                include_callback=True,
                callback_url=callback_url,
                include_content_type=True,
            ),
            json=payload.model_dump(by_alias=True, mode="json"),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
            idempotent=(reference_id is not None),
            reference_id=ref,
        )
        return ref

    async def get_deposit_status(self, reference_id: str) -> TransactionResult:
        """Poll the status of a deposit transaction.

        Args:
            reference_id: The transaction reference ID.

        Returns:
            A TransactionResult object detailing the status of the transaction.
        """
        validate_reference_id(reference_id)
        response = await self._http.request(
            "GET",
            f"/disbursement/v2_0/deposit/{reference_id}",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
            reference_id=reference_id,
        )
        return parse_model(response, TransactionResult, reference_id=reference_id)

    async def refund(
        self,
        amount: str,
        currency: str,
        reference_id_to_refund: str,
        external_id: str,
        *,
        payer_message: str = "",
        payee_note: str = "",
        reference_id: str | None = None,
        callback_url: str | None = None,
    ) -> str:
        """Initiate a Refund (v2).

        Args:
            amount: The transaction amount.
            currency: The transaction currency.
            reference_id_to_refund: The reference ID of the transaction to refund.
            external_id: The external ID.
            payer_message: Message to the payer.
            payee_note: Note to the payee.
            reference_id: Optional client-supplied reference ID.

        Returns:
            The reference ID associated with the refund.
        """
        if reference_id is not None:
            validate_reference_id(reference_id)
        validate_reference_id(reference_id_to_refund)
        ref = reference_id or generate_reference_id()

        payload = RefundRequest(
            amount=amount,
            currency=currency,
            externalId=external_id,
            referenceIdToRefund=reference_id_to_refund,
            payerMessage=payer_message,
            payeeNote=payee_note,
        )

        await self._http.request(
            "POST",
            "/disbursement/v2_0/refund",
            headers=await self._build_headers(
                reference_id=ref,
                include_callback=True,
                callback_url=callback_url,
                include_content_type=True,
            ),
            json=payload.model_dump(by_alias=True, mode="json"),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
            idempotent=(reference_id is not None),
            reference_id=ref,
        )
        return ref

    async def get_refund_status(self, reference_id: str) -> TransactionResult:
        """Poll the status of a refund transaction.

        Args:
            reference_id: The transaction reference ID.

        Returns:
            A TransactionResult object detailing the status of the transaction.
        """
        validate_reference_id(reference_id)
        response = await self._http.request(
            "GET",
            f"/disbursement/v2_0/refund/{reference_id}",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
            reference_id=reference_id,
        )
        return parse_model(response, TransactionResult, reference_id=reference_id)
