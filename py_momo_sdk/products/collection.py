from __future__ import annotations

from py_momo_sdk.http import parse_model
from py_momo_sdk.models import (
    BasicUserInfo,
    BcAuthorizeRequest,
    BcAuthorizeResponse,
    OAuth2TokenResponse,
    Party,
    PreApprovalRequest,
    PreApprovalResult,
    RequestToPayRequest,
    RequestToWithdrawRequest,
    TransactionResult,
    _validate_note_text,
)
from py_momo_sdk.products.base import BaseProduct
from py_momo_sdk.utils import (
    _MSISDN_ALLOWED_CHARS_RE,
    build_basic_auth_header,
    generate_reference_id,
    normalise_msisdn,
    validate_header_value,
    validate_reference_id,
)

_VALID_BC_ACCESS_TYPES = frozenset({"online", "offline"})


class Collection(BaseProduct):
    """Collection product client."""

    _product_name = "collection"
    _token_path = "/collection/token/"  # nosec B105

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
        callback_url: str | None = None,
        party_id_type: str = "MSISDN",
    ) -> str:
        """Initiate a Request to Pay.

        Args:
            amount: The transaction amount.
            currency: The transaction currency.
            payer_msisdn: The MSISDN (or party identifier) of the payer.
            external_id: The external ID.
            payer_message: Message to the payer.
            payee_note: Note to the payee.
            reference_id: Optional client-supplied reference ID.
            callback_url: Optional per-request webhook callback URL.
            party_id_type: Party identifier type (``MSISDN``, ``EMAIL``, or ``PARTY_CODE``).

        Returns:
            The reference ID associated with the transaction.
        """
        if reference_id is not None:
            validate_reference_id(reference_id)
        ref = reference_id or generate_reference_id()
        norm_party_type = party_id_type.strip().upper()
        party_id = (
            normalise_msisdn(payer_msisdn)
            if norm_party_type == "MSISDN"
            else payer_msisdn.strip()
        )

        payload = RequestToPayRequest(
            amount=amount,
            currency=currency,
            externalId=external_id,
            payer=Party(
                partyIdType=norm_party_type,
                partyId=party_id,
            ),
            payerMessage=payer_message,
            payeeNote=payee_note,
        )

        self._http.request(
            "POST",
            "/collection/v1_0/requesttopay",
            headers=self._build_headers(
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
            headers=self._build_headers(reference_id=None),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
            reference_id=reference_id,
        )
        return parse_model(response, TransactionResult, reference_id=reference_id)

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
        callback_url: str | None = None,
        party_id_type: str = "MSISDN",
    ) -> str:
        """Initiate a Request to Withdraw (v2).

        Args:
            amount: The transaction amount.
            currency: The transaction currency.
            payer_msisdn: The MSISDN (or party identifier) of the payer.
            external_id: The external ID.
            payer_message: Message to the payer.
            payee_note: Note to the payee.
            reference_id: Optional client-supplied reference ID.
            callback_url: Optional per-request webhook callback URL.
            party_id_type: Party identifier type (``MSISDN``, ``EMAIL``, or ``PARTY_CODE``).

        Returns:
            The reference ID associated with the withdrawal.
        """
        if reference_id is not None:
            validate_reference_id(reference_id)
        ref = reference_id or generate_reference_id()
        norm_party_type = party_id_type.strip().upper()
        party_id = (
            normalise_msisdn(payer_msisdn)
            if norm_party_type == "MSISDN"
            else payer_msisdn.strip()
        )

        payload = RequestToWithdrawRequest(
            amount=amount,
            currency=currency,
            externalId=external_id,
            payer=Party(
                partyIdType=norm_party_type,
                partyId=party_id,
            ),
            payerMessage=payer_message,
            payeeNote=payee_note,
        )

        self._http.request(
            "POST",
            "/collection/v2_0/requesttowithdraw",
            headers=self._build_headers(
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
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
            reference_id=reference_id,
        )
        return parse_model(response, TransactionResult, reference_id=reference_id)

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
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
        )
        return parse_model(response, BasicUserInfo)

    def bc_authorize(
        self,
        login_hint: str,
        scope: str = "profile",
        access_type: str = "offline",
        *,
        callback_url: str | None = None,
    ) -> BcAuthorizeResponse:
        """Initiate backchannel authorization request.

        Args:
            login_hint: A hint identifying the user (usually 'ID:<msisdn>/MSISDN' or phone number).
            scope: The scope of the request (defaults to 'profile').
            access_type: The access type (``"online"`` or ``"offline"``).
            callback_url: Optional webhook callback URL for async notification.

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
        norm_access_type = access_type.strip().lower()
        if norm_access_type not in _VALID_BC_ACCESS_TYPES:
            raise ValueError("access_type must be 'online' or 'offline'")

        if _MSISDN_ALLOWED_CHARS_RE.fullmatch(login_hint.strip()):
            login_hint = f"ID:{normalise_msisdn(login_hint)}/MSISDN"

        payload = BcAuthorizeRequest(
            login_hint=login_hint,
            scope=scope,
            access_type=norm_access_type,
        )

        headers = self._build_headers(
            include_callback=(callback_url is not None), callback_url=callback_url
        )
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        response = self._http.request(
            "POST",
            "/collection/v1_0/bc-authorize",
            headers=headers,
            data=payload.model_dump(by_alias=True),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
        )
        return parse_model(response, BcAuthorizeResponse)

    def create_oauth2_token(
        self,
        auth_req_id: str | None = None,
        *,
        grant_type: str = "urn:openid:params:grant-type:ciba",
        refresh_token: str | None = None,
    ) -> OAuth2TokenResponse:
        """Exchange a CIBA authorization request ID or refresh token for an OAuth2 user token.

        Args:
            auth_req_id: The ``auth_req_id`` returned by ``bc_authorize()`` (required for CIBA).
            grant_type: OAuth2 grant type (defaults to CIBA; pass ``"refresh_token"`` to refresh).
            refresh_token: Refresh token string when ``grant_type="refresh_token"``.

        Returns:
            An ``OAuth2TokenResponse`` containing the user access token and
            metadata.

        Raises:
            ValueError: If required token grant fields are empty or invalid.
            AuthenticationError: If client credentials are rejected.
        """
        if not isinstance(grant_type, str) or not grant_type.strip():
            raise ValueError("grant_type must be a non-empty string")
        validate_header_value(grant_type, field_name="grant_type")

        form_data: dict[str, str] = {"grant_type": grant_type}
        if grant_type == "refresh_token":
            token_val = refresh_token if refresh_token is not None else auth_req_id
            if not isinstance(token_val, str) or not token_val.strip():
                raise ValueError("refresh_token must be a non-empty string")
            validate_header_value(
                token_val, field_name="refresh_token", allow_whitespace=False
            )
            form_data["refresh_token"] = token_val
        else:
            if not isinstance(auth_req_id, str) or not auth_req_id.strip():
                raise ValueError("auth_req_id must be a non-empty string")
            validate_header_value(auth_req_id, field_name="auth_req_id")
            form_data["auth_req_id"] = auth_req_id

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
        response = self._http.request(
            "POST",
            "/collection/oauth2/token/",
            headers=headers,
            data=form_data,
        )
        return parse_model(response, OAuth2TokenResponse)

    def get_user_info_with_consent(self, oauth2_access_token: str) -> BasicUserInfo:
        """Retrieve consented subscriber info via ``GET /collection/oauth2/v1_0/userinfo``.

        Args:
            oauth2_access_token: User-consent Bearer token returned by ``create_oauth2_token()``.

        Returns:
            A ``BasicUserInfo`` model populated from the MTN OAuth2 userinfo endpoint.
        """
        if not isinstance(oauth2_access_token, str) or not oauth2_access_token.strip():
            raise ValueError("oauth2_access_token must be a non-empty string")
        token_val = validate_header_value(
            oauth2_access_token.strip(),
            field_name="oauth2_access_token",
            allow_whitespace=False,
        )
        headers = {
            "Authorization": f"Bearer {token_val}",
            "Ocp-Apim-Subscription-Key": self._product_config.subscription_key,
            "X-Target-Environment": self._config.environment,
        }
        response = self._http.request(
            "GET",
            "/collection/oauth2/v1_0/userinfo",
            headers=headers,
        )
        return parse_model(response, BasicUserInfo)

    def send_delivery_notification(
        self,
        reference_id: str,
        notification_message: str,
        *,
        language: str | None = None,
    ) -> None:
        """Send an additional SMS/push delivery notification for a Request to Pay.

        Calls ``POST /collection/v1_0/requesttopay/{referenceId}/deliverynotification``.
        """
        validate_reference_id(reference_id)
        cleaned_msg = _validate_note_text(
            notification_message, field_name="notification_message"
        )
        if not cleaned_msg.strip():
            raise ValueError("notification_message must not be blank")
        headers = self._build_headers(include_content_type=True)
        headers["notificationMessage"] = validate_header_value(
            cleaned_msg, field_name="notification_message"
        )
        if language is not None:
            if (
                not isinstance(language, str)
                or len(language.strip()) != 2
                or not language.strip().isascii()
                or not language.strip().isalpha()
            ):
                raise ValueError("language must be a 2-letter ISO language code")
            headers["Language"] = language.strip().lower()
        self._http.request(
            "POST",
            f"/collection/v1_0/requesttopay/{reference_id}/deliverynotification",
            headers=headers,
            json={"notificationMessage": cleaned_msg},
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
            reference_id=reference_id,
        )

    def create_preapproval(
        self,
        payer_msisdn: str,
        payer_currency: str,
        *,
        validity_time: int,
        payer_message: str = "",
        reference_id: str | None = None,
        callback_url: str | None = None,
        party_id_type: str = "MSISDN",
    ) -> str:
        """Request a subscriber PreApproval (``POST /collection/v2_0/preapproval``)."""
        if reference_id is not None:
            validate_reference_id(reference_id)
        ref = reference_id or generate_reference_id()
        party_id = (
            normalise_msisdn(payer_msisdn)
            if party_id_type.upper() == "MSISDN"
            else payer_msisdn
        )
        payload = PreApprovalRequest(
            payer=Party(partyIdType=party_id_type.upper(), partyId=party_id),
            payerCurrency=payer_currency,
            payerMessage=payer_message,
            validityTime=validity_time,
        )
        self._http.request(
            "POST",
            "/collection/v2_0/preapproval",
            headers=self._build_headers(
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

    def get_preapproval_status(self, reference_id: str) -> PreApprovalResult:
        """Query the status of a PreApproval (``GET /collection/v2_0/preapproval/{referenceId}``)."""
        validate_reference_id(reference_id)
        response = self._http.request(
            "GET",
            f"/collection/v2_0/preapproval/{reference_id}",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
            reference_id=reference_id,
        )
        return parse_model(response, PreApprovalResult, reference_id=reference_id)

    def cancel_preapproval(self, reference_id: str) -> None:
        """Cancel an active PreApproval (``DELETE /collection/v2_0/preapproval/{referenceId}``)."""
        validate_reference_id(reference_id)
        self._http.request(
            "DELETE",
            f"/collection/v2_0/preapproval/{reference_id}",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
            reference_id=reference_id,
        )
