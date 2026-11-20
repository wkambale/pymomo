from __future__ import annotations

from pymomo.http import parse_model
from pymomo.models import (
    DepositRequest,
    Party,
    RefundRequest,
    TransactionResult,
    TransferRequest,
)
from pymomo.products.base import BaseProduct
from pymomo.utils import generate_reference_id, normalise_msisdn, validate_reference_id


class Disbursement(BaseProduct):
    """Disbursement product client."""

    _product_name = "disbursement"
    _token_path = "/disbursement/token/"  # nosec B105

    def transfer(
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

        self._http.request(
            "POST",
            "/disbursement/v1_0/transfer",
            headers=self._build_headers(reference_id=ref, include_callback=True),
            json=payload.model_dump(by_alias=True, mode="json"),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return ref

    def get_transfer_status(self, reference_id: str) -> TransactionResult:
        """Poll the status of a transfer transaction.

        Args:
            reference_id: The transaction reference ID.

        Returns:
            A TransactionResult object detailing the status of the transaction.
        """
        validate_reference_id(reference_id)
        response = self._http.request(
            "GET",
            f"/disbursement/v1_0/transfer/{reference_id}",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, TransactionResult)

    def deposit(
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
        """Initiate a Deposit (v2).

        Args:
            amount: The transaction amount.
            currency: The transaction currency.
            payee_msisdn: The MSISDN of the payee.
            external_id: The external ID.
            payer_message: Message to the payer.
            payee_note: Note to the payee.
            reference_id: Optional client-supplied reference ID.

        Returns:
            The reference ID associated with the deposit.
        """
        if reference_id is not None:
            validate_reference_id(reference_id)
        ref = reference_id or generate_reference_id()

        payload = DepositRequest(
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

        self._http.request(
            "POST",
            "/disbursement/v2_0/deposit",
            headers=self._build_headers(reference_id=ref, include_callback=True),
            json=payload.model_dump(by_alias=True, mode="json"),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return ref

    def get_deposit_status(self, reference_id: str) -> TransactionResult:
        """Poll the status of a deposit transaction.

        Args:
            reference_id: The transaction reference ID.

        Returns:
            A TransactionResult object detailing the status of the transaction.
        """
        validate_reference_id(reference_id)
        response = self._http.request(
            "GET",
            f"/disbursement/v2_0/deposit/{reference_id}",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, TransactionResult)

    def refund(
        self,
        amount: str,
        currency: str,
        reference_id_to_refund: str,
        external_id: str,
        *,
        payer_message: str = "",
        payee_note: str = "",
        reference_id: str | None = None,
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

        self._http.request(
            "POST",
            "/disbursement/v2_0/refund",
            headers=self._build_headers(reference_id=ref, include_callback=True),
            json=payload.model_dump(by_alias=True, mode="json"),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return ref

    def get_refund_status(self, reference_id: str) -> TransactionResult:
        """Poll the status of a refund transaction.

        Args:
            reference_id: The transaction reference ID.

        Returns:
            A TransactionResult object detailing the status of the transaction.
        """
        validate_reference_id(reference_id)
        response = self._http.request(
            "GET",
            f"/disbursement/v2_0/refund/{reference_id}",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, TransactionResult)
