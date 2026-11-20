from __future__ import annotations

from pymomo._async.http import AsyncHttpClient
from pymomo.auth import TokenCache
from pymomo.config import MomoConfig, ProductConfig
from pymomo.models import Balance, BasicUserInfo, TokenResponse
from pymomo.utils import build_basic_auth_header, normalise_msisdn


class AsyncBaseProduct:
    """Shared behaviour for all async MoMo product clients."""

    _product_name: (
        str  # Subclasses set this: "collection", "disbursement", "remittance"
    )
    _token_path: str  # Subclasses set this: e.g. "/collection/token/"

    def __init__(
        self,
        config: MomoConfig,
        product_config: ProductConfig,
        http: AsyncHttpClient,
        token_cache: TokenCache,
    ) -> None:
        self._config = config
        self._product_config = product_config
        self._http = http
        self._token_cache = token_cache

    async def _get_token(self) -> str:
        cached = self._token_cache.get(self._product_name)
        if cached:
            return cached
        return await self._fetch_token()

    async def _fetch_token(self) -> str:
        auth_header = build_basic_auth_header(
            self._product_config.api_user,
            self._product_config.api_key,
        )
        response = await self._http.request(
            "POST",
            self._token_path,
            headers={
                "Authorization": auth_header,
                "Ocp-Apim-Subscription-Key": self._product_config.subscription_key,
                "X-Target-Environment": self._config.environment,
            },
        )
        token = TokenResponse.model_validate(response.json())
        self._token_cache.set(
            self._product_name,
            token.access_token,
            token.expires_in,
        )
        return token.access_token

    async def _build_headers(
        self,
        *,
        reference_id: str | None = None,
        include_callback: bool = False,
    ) -> dict[str, str]:
        token = await self._get_token()
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

    async def get_balance(self) -> Balance:
        """Get the current account balance for this product.

        Returns:
            A Balance object containing the available balance and currency.

        Raises:
            AuthenticationError: If the access token cannot be obtained.
            MomoServerError: If the MTN API returns a 5xx error.
        """
        response = await self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/account/balance",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._fetch_token,
        )
        return Balance.model_validate(response.json())

    async def get_balance_for_currency(self, currency: str) -> Balance:
        """Get the account balance for a specific currency.

        Args:
            currency: The ISO currency code.

        Returns:
            A Balance object containing the available balance and currency.
        """
        response = await self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/account/balance/{currency}",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._fetch_token,
        )
        return Balance.model_validate(response.json())

    async def is_account_holder_active(
        self,
        account_holder_id: str,
        account_holder_id_type: str = "msisdn",
    ) -> bool:
        """Check if an account holder is active.

        Args:
            account_holder_id: The account holder identifier.
            account_holder_id_type: The type of identifier (e.g. msisdn, email).

        Returns:
            True if the account holder is active, False otherwise.
        """
        if account_holder_id_type == "msisdn":
            account_holder_id = normalise_msisdn(account_holder_id)
        response = await self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/accountholder"
            f"/{account_holder_id_type}/{account_holder_id}/active",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._fetch_token,
        )
        res = response.json()
        result = res.get("result")
        if isinstance(result, str):
            return result.lower() == "true"
        return bool(result)

    async def get_basic_user_info(
        self,
        account_holder_id: str,
        account_holder_id_type: str = "msisdn",
    ) -> BasicUserInfo:
        """Get basic user info of an account holder.

        Args:
            account_holder_id: The account holder identifier.
            account_holder_id_type: The type of identifier (e.g. msisdn, email).

        Returns:
            A BasicUserInfo object containing name, given_name, locale, etc.
        """
        if account_holder_id_type == "msisdn":
            account_holder_id = normalise_msisdn(account_holder_id)
        response = await self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/accountholder"
            f"/{account_holder_id_type}/{account_holder_id}/basicuserinfo",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._fetch_token,
        )
        return BasicUserInfo.model_validate(response.json())
