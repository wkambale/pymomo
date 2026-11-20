from __future__ import annotations

from typing import TYPE_CHECKING

from py_momo_api._async.http import AsyncHttpClient
from py_momo_api._async.products.collection import Collection
from py_momo_api._async.products.disbursement import Disbursement
from py_momo_api._async.products.remittance import Remittance
from py_momo_api._async.sandbox import AsyncSandboxProvisioner
from py_momo_api.auth import TokenCache
from py_momo_api.config import PyMomoAPIConfig
from py_momo_api.exceptions import MissingCredentialsError, PyMomoAPIError

if TYPE_CHECKING:
    from typing_extensions import Self


class AsyncPyMomoAPI:
    """Asynchronous MTN MoMo API client.

    Instantiate with a PyMomoAPIConfig and access products via attributes.

    Example:
        async with AsyncPyMomoAPI(config) as client:
            balance = await client.collection.get_balance()
    """

    def __init__(self, config: PyMomoAPIConfig) -> None:
        self._config = config
        self._token_cache = TokenCache()
        if not config.base_url:
            raise PyMomoAPIError("Base URL must use HTTPS")
        self._http = AsyncHttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
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
                "Collection credentials not provided in PyMomoAPIConfig"
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
                "Disbursement credentials not provided in PyMomoAPIConfig"
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
                "Remittance credentials not provided in PyMomoAPIConfig"
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
    def sandbox(self) -> AsyncSandboxProvisioner:
        """Get AsyncSandboxProvisioner client instance."""
        return AsyncSandboxProvisioner(
            config=self._config,
            http=self._http,
        )

    def create_sandbox_provisioner(
        self, subscription_key: str
    ) -> AsyncSandboxProvisioner:
        """Create an AsyncSandboxProvisioner using an explicit subscription key.

        Args:
            subscription_key: The sandbox Ocp-Apim-Subscription-Key.

        Returns:
            A configured AsyncSandboxProvisioner sharing this client's HTTP session.
        """
        return AsyncSandboxProvisioner(
            subscription_key=subscription_key,
            config=self._config,
            http=self._http,
        )

    async def close(self) -> None:
        """Close the underlying AsyncHttpClient session."""
        await self._http.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
