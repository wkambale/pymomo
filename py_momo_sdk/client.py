from __future__ import annotations

from typing import TYPE_CHECKING

from py_momo_sdk.auth import TokenCache
from py_momo_sdk.config import PyMomoSDKConfig
from py_momo_sdk.exceptions import MissingCredentialsError, PyMomoSDKError
from py_momo_sdk.http import HttpClient
from py_momo_sdk.products.collection import Collection
from py_momo_sdk.products.disbursement import Disbursement
from py_momo_sdk.products.remittance import Remittance
from py_momo_sdk.sandbox import SandboxProvisioner

if TYPE_CHECKING:
    from typing_extensions import Self


class PyMomoSDK:
    """Synchronous MTN MoMo API client.

    Instantiate with a PyMomoSDKConfig and access products via attributes.

    Example:
        client = PyMomoSDK(
            PyMomoSDKConfig(
                environment="sandbox",
                collection=ProductConfig(
                    subscription_key="...",
                    api_user="...",
                    api_key="...",
                ),
            )
        )
        balance = client.collection.get_balance()
    """

    def __init__(self, config: PyMomoSDKConfig) -> None:
        self._config = config
        self._token_cache = TokenCache()
        if not config.base_url:
            raise PyMomoSDKError("Base URL must use HTTPS")
        self._http = HttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
            retry_backoff=config.retry_backoff,
            telemetry=config.telemetry,
        )
        self._collection: Collection | None = None
        self._disbursement: Disbursement | None = None
        self._remittance: Remittance | None = None

    @property
    def collection(self) -> Collection:
        """Get Collection client instance.

        Raises:
            MissingCredentialsError: If collection credentials are not configured.
        """
        if self._config.collection is None:
            raise MissingCredentialsError(
                "Collection credentials not provided in PyMomoSDKConfig"
            )
        if self._collection is None:
            self._collection = Collection(
                config=self._config,
                product_config=self._config.collection,
                http=self._http,
                token_cache=self._token_cache,
            )
        return self._collection

    @property
    def disbursement(self) -> Disbursement:
        """Get Disbursement client instance.

        Raises:
            MissingCredentialsError: If disbursement credentials are not configured.
        """
        if self._config.disbursement is None:
            raise MissingCredentialsError(
                "Disbursement credentials not provided in PyMomoSDKConfig"
            )
        if self._disbursement is None:
            self._disbursement = Disbursement(
                config=self._config,
                product_config=self._config.disbursement,
                http=self._http,
                token_cache=self._token_cache,
            )
        return self._disbursement

    @property
    def remittance(self) -> Remittance:
        """Get Remittance client instance.

        Raises:
            MissingCredentialsError: If remittance credentials are not configured.
        """
        if self._config.remittance is None:
            raise MissingCredentialsError(
                "Remittance credentials not provided in PyMomoSDKConfig"
            )
        if self._remittance is None:
            self._remittance = Remittance(
                config=self._config,
                product_config=self._config.remittance,
                http=self._http,
                token_cache=self._token_cache,
            )
        return self._remittance

    @property
    def sandbox(self) -> SandboxProvisioner:
        """Get SandboxProvisioner client instance."""
        return SandboxProvisioner(
            config=self._config,
            http=self._http,
        )

    def create_sandbox_provisioner(self, subscription_key: str) -> SandboxProvisioner:
        """Create a SandboxProvisioner using an explicit subscription key.

        Args:
            subscription_key: The sandbox Ocp-Apim-Subscription-Key.

        Returns:
            A configured SandboxProvisioner sharing this client's HTTP session.
        """
        return SandboxProvisioner(
            subscription_key=subscription_key,
            config=self._config,
            http=self._http,
        )

    def close(self) -> None:
        """Close the underlying HttpClient session."""
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
