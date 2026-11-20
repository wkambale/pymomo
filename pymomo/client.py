from __future__ import annotations

from typing import TYPE_CHECKING

from pymomo.auth import TokenCache
from pymomo.config import MomoConfig
from pymomo.exceptions import MissingCredentialsError, PyMoMoError
from pymomo.http import HttpClient
from pymomo.products.collection import Collection
from pymomo.products.disbursement import Disbursement
from pymomo.products.remittance import Remittance
from pymomo.sandbox import SandboxProvisioner

if TYPE_CHECKING:
    from typing_extensions import Self


class MomoClient:
    """Synchronous MTN MoMo API client.

    Instantiate with a MomoConfig and access products via attributes.

    Example:
        client = MomoClient(
            MomoConfig(
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

    def __init__(self, config: MomoConfig) -> None:
        self._config = config
        self._token_cache = TokenCache()
        if not config.base_url:
            raise PyMoMoError("Base URL must use HTTPS")
        self._http = HttpClient(
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
                "Collection credentials not provided in MomoConfig"
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
                "Disbursement credentials not provided in MomoConfig"
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
                "Remittance credentials not provided in MomoConfig"
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

    def close(self) -> None:
        """Close the underlying HttpClient session."""
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
