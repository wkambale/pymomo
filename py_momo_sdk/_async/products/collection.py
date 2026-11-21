from __future__ import annotations

from py_momo_sdk._async.products.base import AsyncBaseProduct
from py_momo_sdk.http import parse_model
from py_momo_sdk.models import (
    BasicUserInfo,
    BcAuthorizeResponse,
    OAuth2TokenResponse,
    Party,
    RequestToPayRequest,
    RequestToWithdrawRequest,
    TransactionResult,
)
from py_momo_sdk.utils import (
    build_basic_auth_header,
    generate_reference_id,
    normalise_msisdn,
    validate_header_value,
    validate_reference_id,
)


class Collection(AsyncBaseProduct):
    """Asynchronous Collection product client."""

    _product_name = "collection"
    _token_path = "/collection/token/"  # nosec B105

    async def request_to_pay(
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

        await self._http.request(
            "POST",
            "/collection/v1_0/requesttopay",
            headers=await self._build_headers(reference_id=ref, include_callback=True),
            json=payload.model_dump(by_alias=True, mode="json"),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return ref

    async def get_payment_status(self, reference_id: str) -> TransactionResult:
        """Poll the status of a Request to Pay transaction.

        Args:
            reference_id: The transaction reference ID.

        Returns:
            A TransactionResult object detailing the status of the transaction.
        """
        validate_reference_id(reference_id)
        response = await self._http.request(
            "GET",
            f"/collection/v1_0/requesttopay/{reference_id}",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, TransactionResult)

    async def request_to_withdraw(
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

        await self._http.request(
            "POST",
            "/collection/v2_0/requesttowithdraw",
            headers=await self._build_headers(reference_id=ref, include_callback=True),
            json=payload.model_dump(by_alias=True, mode="json"),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return ref

    async def get_withdraw_status(self, reference_id: str) -> TransactionResult:
        """Poll the status of a Request to Withdraw transaction.

        Args:
            reference_id: The transaction reference ID.

        Returns:
            A TransactionResult object detailing the status of the transaction.
        """
        validate_reference_id(reference_id)
        response = await self._http.request(
            "GET",
            f"/collection/v2_0/requesttowithdraw/{reference_id}",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, TransactionResult)

    async def get_basic_user_info_by_reference(
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
        response = await self._http.request(
            "GET",
            f"/collection/v2_0/user/{reference_id}/basicuserinfo",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, BasicUserInfo)

    async def bc_authorize(
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
        if not isinstance(login_hint, str) or not login_hint.strip():
            raise ValueError("login_hint must be a non-empty string")
        validate_header_value(login_hint, field_name="login_hint")
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError("scope must be a non-empty string")
        validate_header_value(scope, field_name="scope")
        if not isinstance(access_type, str) or not access_type.strip():
            raise ValueError("access_type must be a non-empty string")
        validate_header_value(access_type, field_name="access_type")

        if (login_hint.isascii() and login_hint.isdigit()) or login_hint.startswith(
            "+"
        ):
            login_hint = f"ID:{normalise_msisdn(login_hint)}/MSISDN"

        from py_momo_sdk.models import BcAuthorizeRequest

        payload = BcAuthorizeRequest(
            login_hint=login_hint,
            scope=scope,
            access_type=access_type,
        )

        headers = await self._build_headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        response = await self._http.request(
            "POST",
            "/collection/v1_0/bc-authorize",
            headers=headers,
            data=payload.model_dump(by_alias=True),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, BcAuthorizeResponse)

    async def create_oauth2_token(
        self,
        auth_req_id: str,
        *,
        grant_type: str = "urn:openid:params:grant-type:ciba",
    ) -> OAuth2TokenResponse:
        """Exchange a CIBA authorization request ID for an OAuth2 user token.

        Args:
            auth_req_id: The ``auth_req_id`` returned by ``bc_authorize()``.
            grant_type: OAuth2 grant type (defaults to CIBA grant type).

        Returns:
            An ``OAuth2TokenResponse`` containing the user access token and
            metadata.

        Raises:
            ValueError: If ``auth_req_id`` or ``grant_type`` is empty or invalid.
            AuthenticationError: If client credentials are rejected.
        """
        if not isinstance(auth_req_id, str) or not auth_req_id.strip():
            raise ValueError("auth_req_id must be a non-empty string")
        validate_header_value(auth_req_id, field_name="auth_req_id")
        if not isinstance(grant_type, str) or not grant_type.strip():
            raise ValueError("grant_type must be a non-empty string")
        validate_header_value(grant_type, field_name="grant_type")

        auth_header = build_basic_auth_header(
            self._product_config.api_user,
            self._product_config.api_key,
        )
        headers = {
            "Authorization": auth_header,
            "Ocp-Apim-Subscription-Key": self._product_config.subscription_key,
            "X-Target-Environment": self._config.environment,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = await self._http.request(
            "POST",
            "/collection/v1_0/oauth2/token/",
            headers=headers,
            data={
                "grant_type": grant_type,
                "auth_req_id": auth_req_id,
            },
        )
        return parse_model(response, OAuth2TokenResponse)
