from __future__ import annotations

from pymomo.config import SANDBOX, MomoConfig
from pymomo.exceptions import MissingCredentialsError, PyMoMoError
from pymomo.http import HttpClient, parse_json_dict
from pymomo.models import ApiKeyResult, ApiUserInfo
from pymomo.utils import generate_reference_id, validate_reference_id


class SandboxProvisioner:
    """Provisions sandbox API users and API keys.

    This class uses its own subscription key (provided at instantiation)
    rather than per-product credentials, because the sandbox endpoints
    sit outside the product hierarchy.
    """

    _http: HttpClient
    _config: MomoConfig | None
    _subscription_key: str

    def __init__(
        self,
        subscription_key: str | MomoConfig | None = None,
        config: MomoConfig | HttpClient | None = None,
        http: HttpClient | None = None,
    ) -> None:
        from typing import cast

        if isinstance(subscription_key, MomoConfig):
            # Property-based invocation: SandboxProvisioner(config, http)
            self._config = subscription_key
            self._http = cast(HttpClient, config)
            self._subscription_key = self._extract_sub_key(self._config)
        elif subscription_key is None and isinstance(config, MomoConfig):
            # Keyword-based invocation: SandboxProvisioner(config=config, http=http)
            self._config = config
            self._http = cast(HttpClient, http)
            self._subscription_key = self._extract_sub_key(self._config)
        else:
            # Standard instantiation: SandboxProvisioner(subscription_key, config, http)
            self._subscription_key = subscription_key or ""
            self._config = cast("MomoConfig | None", config)
            self._http = cast(HttpClient, http)

        if self._http is None:
            raise PyMoMoError("HTTP client is required for sandbox provisioning")
        if self._config is not None and self._config.environment != SANDBOX:
            raise PyMoMoError(
                "SandboxProvisioner can only be used with the sandbox environment"
            )
        if not self._subscription_key:
            raise MissingCredentialsError(
                "Subscription key is required for sandbox provisioning"
            )

    def __repr__(self) -> str:
        env = self._config.environment if self._config else None
        return f"SandboxProvisioner(subscription_key=<redacted>, environment={env!r})"

    def __str__(self) -> str:
        return self.__repr__()

    def _extract_sub_key(self, config: MomoConfig) -> str:
        return (
            (config.collection.subscription_key if config.collection else "")
            or (config.disbursement.subscription_key if config.disbursement else "")
            or (config.remittance.subscription_key if config.remittance else "")
        )

    def create_api_user(
        self,
        api_user: str | None = None,
        *,
        callback_host: str = "https://pymomo.aiforuganda.org",
    ) -> str:
        """Create a sandbox API user. Returns the api_user UUID."""
        if api_user is not None:
            validate_reference_id(api_user)
        ref = api_user or generate_reference_id()
        self._http.request(
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

    def get_api_user(self, api_user: str) -> ApiUserInfo:
        """Get information about a sandbox API user.

        Args:
            api_user: The API user UUID.

        Returns:
            An ApiUserInfo object containing provider callback host, etc.
        """
        validate_reference_id(api_user)
        response = self._http.request(
            "GET",
            f"/v1_0/apiuser/{api_user}",
            headers={
                "Ocp-Apim-Subscription-Key": self._subscription_key,
            },
        )
        return ApiUserInfo.model_validate(parse_json_dict(response))

    def create_api_key(self, api_user: str) -> str:
        """Create an API key for an existing sandbox user. Returns the api_key."""
        validate_reference_id(api_user)
        response = self._http.request(
            "POST",
            f"/v1_0/apiuser/{api_user}/apikey",
            headers={
                "Ocp-Apim-Subscription-Key": self._subscription_key,
            },
        )
        result = ApiKeyResult.model_validate(parse_json_dict(response))
        return result.api_key

    def provision(
        self,
        *,
        callback_host: str = "https://pymomo.aiforuganda.org",
    ) -> dict[str, str]:
        """Create a user and key in a single call. Returns both values.

        Convenience method for bootstrapping a sandbox environment.
        Returns {"api_user": "...", "api_key": "..."}.
        """
        api_user = self.create_api_user(callback_host=callback_host)
        api_key = self.create_api_key(api_user)
        return {"api_user": api_user, "api_key": api_key}
