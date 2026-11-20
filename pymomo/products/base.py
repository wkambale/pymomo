from __future__ import annotations

import threading

from pymomo.auth import TokenCache
from pymomo.config import MomoConfig, ProductConfig
from pymomo.exceptions import AuthenticationError, PyMoMoError
from pymomo.http import HttpClient, parse_json_dict, parse_model
from pymomo.models import AccountHolderIdType, Balance, BasicUserInfo, TokenResponse
from pymomo.utils import (
    build_basic_auth_header,
    encode_path_segment,
    normalise_msisdn,
    validate_account_holder_id_type,
    validate_currency,
)


class BaseProduct:
    """Shared behaviour for all MoMo product clients."""

    _product_name: (
        str  # Subclasses set this: "collection", "disbursement", "remittance"
    )
    _token_path: str  # Subclasses set this: e.g. "/collection/token/"

    def __init__(
        self,
        config: MomoConfig,
        product_config: ProductConfig,
        http: HttpClient,
        token_cache: TokenCache,
    ) -> None:
        self._config = config
        self._product_config = product_config
        self._http = http
        self._token_cache = token_cache
        self._token_lock = threading.Lock()

    def _get_token(self) -> str:
        cached = self._token_cache.get(self._product_name)
        if cached:
            return cached
        with self._token_lock:
            cached = self._token_cache.get(self._product_name)
            if cached:
                return cached
            return self._fetch_token()

    def _fetch_token(self) -> str:
        auth_header = build_basic_auth_header(
            self._product_config.api_user,
            self._product_config.api_key,
        )
        response = self._http.request(
            "POST",
            self._token_path,
            headers={
                "Authorization": auth_header,
                "Ocp-Apim-Subscription-Key": self._product_config.subscription_key,
                "X-Target-Environment": self._config.environment,
            },
        )
        try:
            token = parse_model(response, TokenResponse)
        except PyMoMoError:
            raise AuthenticationError("Invalid token response from API") from None
        self._token_cache.set(
            self._product_name,
            token.access_token,
            token.expires_in,
        )
        return token.access_token

    def _build_headers(
        self,
        *,
        reference_id: str | None = None,
        include_callback: bool = False,
    ) -> dict[str, str]:
        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Ocp-Apim-Subscription-Key": self._product_config.subscription_key,
            "X-Target-Environment": self._config.environment,
            "Content-Type": "application/json",
        }
        if reference_id:
            headers["X-Reference-Id"] = reference_id
        if include_callback and self._product_config.callback_url:
            headers["X-Callback-Url"] = self._product_config.callback_url
        return headers

    def get_balance(self) -> Balance:
        """Get the current account balance for this product.

        Returns:
            A Balance object containing the available balance and currency.

        Raises:
            AuthenticationError: If the access token cannot be obtained.
            MomoServerError: If the MTN API returns a 5xx error.
        """
        response = self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/account/balance",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, Balance)

    def get_balance_for_currency(self, currency: str) -> Balance:
        """Get the account balance for a specific currency.

        Args:
            currency: The ISO currency code.

        Returns:
            A Balance object containing the available balance and currency.
        """
        validated_currency = validate_currency(currency)
        response = self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/account/balance/{validated_currency}",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, Balance)

    def is_account_holder_active(
        self,
        account_holder_id: str,
        account_holder_id_type: str | AccountHolderIdType = "msisdn",
    ) -> bool:
        """Check if an account holder is active.

        Args:
            account_holder_id: The account holder identifier.
            account_holder_id_type: The type of identifier (e.g. msisdn, email).

        Returns:
            True if the account holder is active, False otherwise.
        """
        id_type = validate_account_holder_id_type(account_holder_id_type)
        if id_type == "msisdn":
            account_holder_id = normalise_msisdn(account_holder_id)
        encoded_id = encode_path_segment(
            account_holder_id, field_name="account_holder_id"
        )
        response = self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/accountholder"
            f"/{id_type}/{encoded_id}/active",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        res = parse_json_dict(response)
        result = res.get("result")
        if isinstance(result, str):
            return result.lower() == "true"
        return bool(result)

    def get_basic_user_info(
        self,
        account_holder_id: str,
        account_holder_id_type: str | AccountHolderIdType = "msisdn",
    ) -> BasicUserInfo:
        """Get basic user info of an account holder.

        Args:
            account_holder_id: The account holder identifier.
            account_holder_id_type: The type of identifier (e.g. msisdn, email).

        Returns:
            A BasicUserInfo object containing name, given_name, locale, etc.
        """
        id_type = validate_account_holder_id_type(account_holder_id_type)
        if id_type == "msisdn":
            account_holder_id = normalise_msisdn(account_holder_id)
        encoded_id = encode_path_segment(
            account_holder_id, field_name="account_holder_id"
        )
        response = self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/accountholder"
            f"/{id_type}/{encoded_id}/basicuserinfo",
            headers=self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
        )
        return parse_model(response, BasicUserInfo)
