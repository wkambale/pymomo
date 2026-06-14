from __future__ import annotations

from pymomo._async.http import AsyncHttpClient
from pymomo.config import MomoConfig
from pymomo.models import ApiKeyResult, ApiUserInfo
from pymomo.utils import generate_reference_id, validate_reference_id


class AsyncSandboxProvisioner:
    """Provisions sandbox API users and API keys asynchronously.

    This class uses its own subscription key (provided at instantiation)
    rather than per-product credentials, because the sandbox endpoints
    sit outside the product hierarchy.
    """

    _http: AsyncHttpClient
    _config: MomoConfig | None
    _subscription_key: str

    def __init__(
        self,
        subscription_key: str | MomoConfig | None = None,
        config: MomoConfig | AsyncHttpClient | None = None,
        http: AsyncHttpClient | None = None,
    ) -> None:
        from typing import cast

        if isinstance(subscription_key, MomoConfig):
            # Property-based invocation: SandboxProvisioner(config, http)
            self._config = subscription_key
            self._http = cast(AsyncHttpClient, config)
            self._subscription_key = self._extract_sub_key(self._config)
        elif subscription_key is None and isinstance(config, MomoConfig):
            # Keyword-based invocation: SandboxProvisioner(config=config, http=http)
            self._config = config
            self._http = cast(AsyncHttpClient, http)
            self._subscription_key = self._extract_sub_key(self._config)
        else:
            # Standard instantiation: SandboxProvisioner(subscription_key, config, http)
            self._subscription_key = subscription_key or ""
            self._config = cast("MomoConfig | None", config)
            self._http = cast(AsyncHttpClient, http)

    def _extract_sub_key(self, config: MomoConfig) -> str:
        return (
            (config.collection.subscription_key if config.collection else "")
            or (config.disbursement.subscription_key if config.disbursement else "")
            or (config.remittance.subscription_key if config.remittance else "")
        )

    async def create_api_user(
        self,
        api_user: str | None = None,
        *,
        callback_host: str = "https://webhook.site",
    ) -> str:
        """Create a sandbox API user asynchronously. Returns the api_user UUID."""
        if api_user is not None:
            validate_reference_id(api_user)
        ref = api_user or generate_reference_id()
        await self._http.request(
            "POST",
            "/v1_0/apiuser",
            headers={
                "X-Reference-Id": ref,
                "Ocp-Apim-Subscription-Key": self._subscription_key,
                "Content-Type": "application/json",
            },
            json={"providerCallbackHost": callback_host},
        )
        return ref

    async def get_api_user(self, api_user: str) -> ApiUserInfo:
        """Get information about a sandbox API user asynchronously.

        Args:
            api_user: The API user UUID.

        Returns:
            An ApiUserInfo object containing provider callback host, etc.
        """
        validate_reference_id(api_user)
        response = await self._http.request(
            "GET",
            f"/v1_0/apiuser/{api_user}",
            headers={
                "Ocp-Apim-Subscription-Key": self._subscription_key,
            },
        )
        return ApiUserInfo.model_validate(response.json())

    async def create_api_key(self, api_user: str) -> str:
        """Create an API key for an existing sandbox user. Returns the api_key."""
        validate_reference_id(api_user)
        response = await self._http.request(
            "POST",
            f"/v1_0/apiuser/{api_user}/apikey",
            headers={
                "Ocp-Apim-Subscription-Key": self._subscription_key,
            },
        )
        result = ApiKeyResult.model_validate(response.json())
        return result.api_key

    async def provision(
        self,
        *,
        callback_host: str = "https://webhook.site",
    ) -> dict[str, str]:
        """Create a user and key in a single call. Returns both values.

        Convenience method for bootstrapping a sandbox environment.
        Returns {"api_user": "...", "api_key": "..."}.
        """
        api_user = await self.create_api_user(callback_host=callback_host)
        api_key = await self.create_api_key(api_user)
        return {"api_user": api_user, "api_key": api_key}
