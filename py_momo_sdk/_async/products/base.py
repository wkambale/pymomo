from __future__ import annotations

import asyncio
import threading
import weakref

from py_momo_sdk._async.http import AsyncHttpClient
from py_momo_sdk.auth import TokenCache
from py_momo_sdk.config import SANDBOX, ProductConfig, PyMomoSDKConfig
from py_momo_sdk.exceptions import AuthenticationError, PyMomoSDKError
from py_momo_sdk.http import parse_json_dict, parse_model
from py_momo_sdk.models import (
    AccountHolderIdType,
    Balance,
    BasicUserInfo,
    TokenResponse,
)
from py_momo_sdk.utils import (
    build_basic_auth_header,
    encode_path_segment,
    normalise_msisdn,
    validate_account_holder_id_type,
    validate_callback_url,
    validate_currency,
)


class AsyncBaseProduct:
    """Shared behaviour for all async MoMo product clients."""

    _product_name: (
        str  # Subclasses set this: "collection", "disbursement", "remittance"
    )
    _token_path: str  # Subclasses set this: e.g. "/collection/token/"

    def __init__(
        self,
        config: PyMomoSDKConfig,
        product_config: ProductConfig,
        http: AsyncHttpClient,
        token_cache: TokenCache,
    ) -> None:
        self._config = config
        self._product_config = product_config
        self._http = http
        self._token_cache = token_cache
        self._token_namespace = f"{config.environment}:{config.base_url or ''}"
        self._loop_locks: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, asyncio.Lock
        ] = weakref.WeakKeyDictionary()
        self._loop_locks_guard = threading.Lock()

    def _get_token_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        with self._loop_locks_guard:
            lock = self._loop_locks.get(loop)
            if lock is None:
                lock = asyncio.Lock()
                self._loop_locks[loop] = lock
            return lock

    async def _get_token(self) -> str:
        cached = self._token_cache.get(
            self._product_name, namespace=self._token_namespace
        )
        if cached:
            return cached
        lock = self._get_token_lock()
        try:
            await asyncio.wait_for(lock.acquire(), timeout=self._config.timeout)
        except asyncio.TimeoutError:
            raise PyMomoSDKError("Timed out waiting for OAuth token refresh") from None
        try:
            cached = self._token_cache.get(
                self._product_name, namespace=self._token_namespace
            )
            if cached:
                return cached
            return await self._fetch_token()
        finally:
            lock.release()

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
            idempotent=True,
        )
        try:
            token = parse_model(response, TokenResponse)
        except PyMomoSDKError:
            raise AuthenticationError("Invalid token response from API") from None
        self._token_cache.set(
            self._product_name,
            token.access_token,
            token.expires_in,
            namespace=self._token_namespace,
        )
        return token.access_token

    async def _build_headers(
        self,
        *,
        reference_id: str | None = None,
        include_callback: bool = False,
        callback_url: str | None = None,
        include_content_type: bool = False,
    ) -> dict[str, str]:
        try:
            token = await self._get_token()
        except PyMomoSDKError as exc:
            if exc.reference_id is None and reference_id is not None:
                exc.reference_id = reference_id
            raise
        headers = {
            "Authorization": f"Bearer {token}",
            "Ocp-Apim-Subscription-Key": self._product_config.subscription_key,
            "X-Target-Environment": self._config.environment,
        }
        if include_content_type:
            headers["Content-Type"] = "application/json"
        if reference_id:
            headers["X-Reference-Id"] = reference_id
        if include_callback:
            allow_localhost = self._config.environment == SANDBOX
            resolved_cb = (
                validate_callback_url(callback_url, allow_localhost=allow_localhost)
                if callback_url is not None
                else self._product_config.callback_url
            )
            if resolved_cb:
                headers["X-Callback-Url"] = resolved_cb
        return headers

    async def get_balance(self) -> Balance:
        """Get the current account balance for this product.

        Returns:
            A Balance object containing the available balance and currency.

        Raises:
            AuthenticationError: If the access token cannot be obtained.
            PyMomoSDKServerError: If the MTN API returns a 5xx error.
        """
        response = await self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/account/balance",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
        )
        return parse_model(response, Balance)

    async def get_balance_for_currency(self, currency: str) -> Balance:
        """Get the account balance for a specific currency.

        Args:
            currency: The ISO currency code.

        Returns:
            A Balance object containing the available balance and currency.
        """
        validated_currency = validate_currency(currency)
        response = await self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/account/balance/{validated_currency}",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
        )
        return parse_model(response, Balance)

    async def is_account_holder_active(
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
        response = await self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/accountholder"
            f"/{id_type}/{encoded_id}/active",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
        )
        res = parse_json_dict(response)
        result = res.get("result")
        if type(result) is bool:
            return result
        if isinstance(result, str) and result.strip().lower() in ("true", "false"):
            return result.strip().lower() == "true"
        raise PyMomoSDKError(
            "Malformed account holder active response: expected boolean 'result'"
        )

    async def get_basic_user_info(
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
        response = await self._http.request(
            "GET",
            f"/{self._product_name}/v1_0/accountholder"
            f"/{id_type}/{encoded_id}/basicuserinfo",
            headers=await self._build_headers(),
            product_name=self._product_name,
            token_cache=self._token_cache,
            token_refresher=self._get_token,
            token_namespace=self._token_namespace,
        )
        return parse_model(response, BasicUserInfo)
