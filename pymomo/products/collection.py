from __future__ import annotations

from pymomo.models import (
    BasicUserInfo,
    BcAuthorizeResponse,
    Party,
    RequestToPayRequest,
    RequestToWithdrawRequest,
    TransactionResult,
)
from pymomo.products.base import BaseProduct
from pymomo.utils import generate_reference_id, normalise_msisdn, validate_reference_id


class Collection(BaseProduct):
    """Collection product client."""

    _product_name = "collection"
    _token_path = "/collection/token/"

    def request_to_pay(
        self,
        amount: str,
        currency: str,
        payer_msisdn: str,
        external_id: str,
        *,
        payer_message: str = "",
        payee_note: str = "",
        reference_id: str | None = None,
    ) -> str:
        """Initiate a Request to Pay.

        Args:
            amount: The transaction amount.
            currency: The transaction currency.
            payer_msisdn: The MSISDN of the payer.
            external_id: The external ID.
            payer_message: Message to the payer.
            payee_note: Note to the payee.
            reference_id: Optional client-supplied reference ID.

        Returns:
            The reference ID associated with the transaction.
        """
        if reference_id is not None:
            validate_reference_id(reference_id)
        ref = reference_id or generate_reference_id()

        payload = RequestToPayRequest(
            amount=amount,
            currency=currency,
            externalId=external_id,
            payer=Party(
                partyIdType="MSISDN",
                partyId=normalise_msisdn(payer_msisdn),
            ),
            payerMessage=payer_message,
            payeeNote=payee_note,
        )

        self._http.request(
            "POST",
            "/collection/v1_0/requesttopay",
            headers=self._build_headers(reference_id=ref, include_callback=True),
            json=payload.model_dump(by_alias=True, mode="json"),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._fetch_token,
        )
        return ref

    def get_payment_status(self, reference_id: str) -> TransactionResult:
        """Poll the status of a Request to Pay transaction.

        Args:
            reference_id: The transaction reference ID.

        Returns:
            A TransactionResult object detailing the status of the transaction.
        """
        validate_reference_id(reference_id)
        response = self._http.request(
            "GET",
            f"/collection/v1_0/requesttopay/{reference_id}",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._fetch_token,
        )
        return TransactionResult.model_validate(response.json())

    def request_to_withdraw(
        self,
        amount: str,
        currency: str,
        payer_msisdn: str,
        external_id: str,
        *,
        payer_message: str = "",
        payee_note: str = "",
        reference_id: str | None = None,
    ) -> str:
        """Initiate a Request to Withdraw (v2).

        Args:
            amount: The transaction amount.
            currency: The transaction currency.
            payer_msisdn: The MSISDN of the payer.
            external_id: The external ID.
            payer_message: Message to the payer.
            payee_note: Note to the payee.
            reference_id: Optional client-supplied reference ID.

        Returns:
            The reference ID associated with the withdrawal.
        """
        if reference_id is not None:
            validate_reference_id(reference_id)
        ref = reference_id or generate_reference_id()

        payload = RequestToWithdrawRequest(
            amount=amount,
            currency=currency,
            externalId=external_id,
            payer=Party(
                partyIdType="MSISDN",
                partyId=normalise_msisdn(payer_msisdn),
            ),
            payerMessage=payer_message,
            payeeNote=payee_note,
        )

        self._http.request(
            "POST",
            "/collection/v2_0/requesttowithdraw",
            headers=self._build_headers(reference_id=ref, include_callback=True),
            json=payload.model_dump(by_alias=True, mode="json"),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._fetch_token,
        )
        return ref

    def get_withdraw_status(self, reference_id: str) -> TransactionResult:
        """Poll the status of a Request to Withdraw transaction.

        Args:
            reference_id: The transaction reference ID.

        Returns:
            A TransactionResult object detailing the status of the transaction.
        """
        validate_reference_id(reference_id)
        response = self._http.request(
            "GET",
            f"/collection/v2_0/requesttowithdraw/{reference_id}",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._fetch_token,
        )
        return TransactionResult.model_validate(response.json())

    def get_basic_user_info_by_reference(
        self,
        reference_id: str,
    ) -> BasicUserInfo:
        """Get basic user info using a reference ID.

        Args:
            reference_id: The reference ID of the user.

        Returns:
            A BasicUserInfo object containing name, given_name, locale, etc.
        """
        validate_reference_id(reference_id)
        response = self._http.request(
            "GET",
            f"/collection/v2_0/user/{reference_id}/basicuserinfo",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._fetch_token,
        )
        return BasicUserInfo.model_validate(response.json())

    def bc_authorize(
        self,
        login_hint: str,
        scope: str = "profile",
        access_type: str = "offline",
    ) -> BcAuthorizeResponse:
        """Initiate backchannel authorization request.

        Args:
            login_hint: A hint identifying the user (usually 'ID:<msisdn>/MSISDN' or phone number).
            scope: The scope of the request (defaults to 'profile').
            access_type: The access type (defaults to 'offline').

        Returns:
            A BcAuthorizeResponse containing auth_req_id and details.
        """
        if login_hint.isdigit() or login_hint.startswith("+"):
            login_hint = f"ID:{normalise_msisdn(login_hint)}/MSISDN"

        from pymomo.models import BcAuthorizeRequest, BcAuthorizeResponse

        payload = BcAuthorizeRequest(
            login_hint=login_hint,
            scope=scope,
            access_type=access_type,
        )

        headers = self._build_headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        response = self._http.request(
            "POST",
            "/collection/v1_0/bc-authorize",
            headers=headers,
            data=payload.model_dump(by_alias=True),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._fetch_token,
        )
        return BcAuthorizeResponse.model_validate(response.json())
