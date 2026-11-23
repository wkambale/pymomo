from __future__ import annotations

from urllib.parse import urlsplit

from py_momo_sdk.config import PRODUCTION_BASE_URL, SANDBOX, PyMomoSDKConfig
from py_momo_sdk.exceptions import MissingCredentialsError, PyMomoSDKError
from py_momo_sdk.http import HttpClient, parse_model
from py_momo_sdk.models import ApiKeyResult, ApiUserInfo
from py_momo_sdk.utils import (
    generate_reference_id,
    validate_callback_host,
    validate_header_value,
    validate_reference_id,
)

_PRODUCTION_HOST = (urlsplit(PRODUCTION_BASE_URL).hostname or "").lower()


class ProvisionResult(dict[str, str]):
    """Dictionary-compatible sandbox provisioning result that redacts credentials on repr/str."""

    def __repr__(self) -> str:
        return "ProvisionResult(api_user=<redacted>, api_key=<redacted>)"

    def __str__(self) -> str:
        return self.__repr__()


class SandboxProvisioner:
    """Provisions sandbox API users and API keys.

    This class uses its own subscription key (provided at instantiation)
    rather than per-product credentials, because the sandbox endpoints
    sit outside the product hierarchy.
    """

    _http: HttpClient
    _config: PyMomoSDKConfig | None
    _subscription_key: str

    def __init__(
        self,
        subscription_key: str | PyMomoSDKConfig | None = None,
        config: PyMomoSDKConfig | HttpClient | None = None,
        http: HttpClient | None = None,
    ) -> None:
        from typing import cast

        if isinstance(subscription_key, PyMomoSDKConfig):
            # Property-based or mixed invocation: SandboxProvisioner(config, http) or SandboxProvisioner(config, http=http)
            self._config = subscription_key
            self._http = cast(
                HttpClient, config if isinstance(config, HttpClient) else http
            )
            self._subscription_key = self._extract_sub_key(self._config)
        elif subscription_key is None and isinstance(config, PyMomoSDKConfig):
            # Keyword-based invocation: SandboxProvisioner(config=config, http=http)
            self._config = config
            self._http = cast(HttpClient, http)
            self._subscription_key = self._extract_sub_key(self._config)
        elif (
            isinstance(subscription_key, str)
            and isinstance(config, HttpClient)
            and http is None
        ):
            # Positional invocation: SandboxProvisioner(subscription_key, http)
            self._subscription_key = subscription_key
            self._config = None
            self._http = config
        else:
            # Standard instantiation: SandboxProvisioner(subscription_key, config, http)
            self._subscription_key = (
                subscription_key if isinstance(subscription_key, str) else ""
            )
            self._config = cast("PyMomoSDKConfig | None", config)
            self._http = cast(HttpClient, http)

        if not isinstance(self._http, HttpClient):
            raise PyMomoSDKError("HTTP client is required for sandbox provisioning")
        if self._config is not None:
            if not isinstance(self._config, PyMomoSDKConfig):
                raise PyMomoSDKError("Invalid configuration for sandbox provisioning")
            if self._config.environment != SANDBOX:
                raise PyMomoSDKError(
                    "SandboxProvisioner can only be used with the sandbox environment"
                )
        for target_url in (
            self._http._validated_base_url,
            str(self._http._client.base_url),
        ):
            if (
                target_url
                and (urlsplit(target_url).hostname or "").lower() == _PRODUCTION_HOST
            ):
                raise PyMomoSDKError(
                    "SandboxProvisioner can only be used with the sandbox environment"
                )
        if not self._subscription_key or not self._subscription_key.strip():
            raise MissingCredentialsError(
                "Subscription key is required for sandbox provisioning"
            )
        validate_header_value(self._subscription_key, field_name="subscription_key")

    def __repr__(self) -> str:
        env = self._config.environment if self._config else None
        return f"SandboxProvisioner(subscription_key=<redacted>, environment={env!r})"

    def __str__(self) -> str:
        return self.__repr__()

    def _extract_sub_key(self, config: PyMomoSDKConfig) -> str:
        return (
            (config.collection.subscription_key if config.collection else "")
            or (config.disbursement.subscription_key if config.disbursement else "")
            or (config.remittance.subscription_key if config.remittance else "")
        )

    def create_api_user(
        self,
        api_user: str | None = None,
        *,
        callback_host: str = "example.com",
    ) -> str:
        """Create a sandbox API user. Returns the api_user UUID."""
        validate_callback_host(callback_host)
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
        return parse_model(response, ApiUserInfo)

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
        result = parse_model(response, ApiKeyResult)
        return result.api_key

    def provision(
        self,
        *,
        callback_host: str = "example.com",
    ) -> ProvisionResult:
        """Create a user and key in a single call. Returns both values.

        Convenience method for bootstrapping a sandbox environment.
        Returns a ``ProvisionResult`` mapping with ``"api_user"`` and ``"api_key"``
        keys whose ``repr()`` / ``str()`` redacts both credentials.
        """
        api_user = self.create_api_user(callback_host=callback_host)
        api_key = self.create_api_key(api_user)
        return ProvisionResult(api_user=api_user, api_key=api_key)
