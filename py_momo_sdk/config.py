from __future__ import annotations

import os
from dataclasses import dataclass

from py_momo_sdk.exceptions import MissingCredentialsError
from py_momo_sdk.telemetry import TelemetryHook
from py_momo_sdk.utils import (
    validate_base_url,
    validate_callback_url,
    validate_environment_name,
    validate_header_value,
    validate_max_retries,
    validate_retry_backoff,
    validate_timeout,
)

# Environment string constants
SANDBOX = "sandbox"
MTN_GHANA = "mtnghana"
MTN_UGANDA = "mtnuganda"
MTN_CONGO = "mtncongo"
MTN_IVORY_COAST = "mtnivorycoast"
MTN_CAMEROON = "mtncameroon"
MTN_ZAMBIA = "mtnzambia"
MTN_BENIN = "mtnbenin"
MTN_SWAZILAND = "mtnswaziland"
MTN_GUINEA_CONAKRY = "mtnguineaconakry"
MTN_SOUTH_AFRICA = "mtnsouthafrica"
MTN_LIBERIA = "mtnliberia"
MTN_RWANDA = "mtnrwanda"

SANDBOX_BASE_URL = "https://sandbox.momodeveloper.mtn.com"
PRODUCTION_BASE_URL = "https://proxy.momoapi.mtn.com"
ONE_API_PRODUCTION_BASE_URL = "https://momoapi.momo.africa"


@dataclass(frozen=True)
class ProductConfig:
    """Credentials and settings for a single MoMo product."""

    subscription_key: str
    api_user: str
    api_key: str
    callback_url: str | None = None

    def __post_init__(self) -> None:
        for field_name, val in (
            ("subscription_key", self.subscription_key),
            ("api_user", self.api_user),
            ("api_key", self.api_key),
        ):
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            validate_header_value(val, field_name=field_name)
        if ":" in self.api_user:
            raise ValueError("api_user must not contain ':'")
        if self.callback_url is not None:
            validate_callback_url(self.callback_url)

    def __repr__(self) -> str:
        return (
            "ProductConfig(api_user=<redacted>, "
            "api_key=<redacted>, subscription_key=<redacted>)"
        )

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True)
class PyMomoSDKConfig:
    """Top-level configuration for a PyMomoSDK instance."""

    environment: str = SANDBOX
    base_url: str | None = None  # Override for testing
    timeout: float = 30.0
    max_retries: int = 0
    retry_backoff: float = 0.5
    collection: ProductConfig | None = None
    disbursement: ProductConfig | None = None
    remittance: ProductConfig | None = None
    telemetry: TelemetryHook | None = None

    def __post_init__(self) -> None:
        validate_environment_name(self.environment)
        allow_localhost = self.environment == SANDBOX
        object.__setattr__(self, "timeout", validate_timeout(self.timeout))
        object.__setattr__(self, "max_retries", validate_max_retries(self.max_retries))
        object.__setattr__(
            self, "retry_backoff", validate_retry_backoff(self.retry_backoff)
        )
        if self.base_url is None:
            object.__setattr__(
                self,
                "base_url",
                (
                    SANDBOX_BASE_URL
                    if self.environment == SANDBOX
                    else PRODUCTION_BASE_URL
                ),
            )
        else:
            validate_base_url(self.base_url, allow_localhost=allow_localhost)
        for product_cfg in (self.collection, self.disbursement, self.remittance):
            if product_cfg is not None and product_cfg.callback_url is not None:
                validate_callback_url(
                    product_cfg.callback_url, allow_localhost=allow_localhost
                )

    @staticmethod
    def _env_stripped(name: str) -> str | None:
        raw = os.environ.get(name)
        if raw is None:
            return None
        stripped = raw.strip()
        return stripped or None

    @classmethod
    def _product_from_env(cls, prefix: str, product_label: str) -> ProductConfig | None:
        sub = cls._env_stripped(f"{prefix}_SUBSCRIPTION_KEY")
        user = cls._env_stripped(f"{prefix}_API_USER")
        key = cls._env_stripped(f"{prefix}_API_KEY")
        cb = cls._env_stripped(f"{prefix}_CALLBACK_URL")
        if not (sub or user or key):
            return None
        if not (sub and user and key):
            raise MissingCredentialsError(
                f"Incomplete {product_label} credentials in environment variables"
            )
        return ProductConfig(
            subscription_key=sub,
            api_user=user,
            api_key=key,
            callback_url=cb,
        )

    @classmethod
    def from_env(cls) -> PyMomoSDKConfig:
        """Create a PyMomoSDKConfig instance by reading environment variables.

        Reads ``PY_MOMO_SDK_ENVIRONMENT``, ``PY_MOMO_SDK_BASE_URL``,
        ``PY_MOMO_SDK_TIMEOUT``, ``PY_MOMO_SDK_MAX_RETRIES``,
        ``PY_MOMO_SDK_RETRY_BACKOFF``, and per-product credentials.

        Returns:
            A PyMomoSDKConfig instance populated with environment variable values.

        Raises:
            ValueError: If numeric env vars are invalid.
            MissingCredentialsError: If a product is only partially configured.
        """
        env = cls._env_stripped("PY_MOMO_SDK_ENVIRONMENT") or SANDBOX
        base_url = cls._env_stripped("PY_MOMO_SDK_BASE_URL")
        timeout_str = cls._env_stripped("PY_MOMO_SDK_TIMEOUT")
        if timeout_str:
            try:
                timeout = validate_timeout(float(timeout_str))
            except ValueError as exc:
                raise ValueError(
                    "PY_MOMO_SDK_TIMEOUT must be a positive finite number"
                ) from exc
        else:
            timeout = 30.0

        retries_str = cls._env_stripped("PY_MOMO_SDK_MAX_RETRIES")
        if retries_str:
            try:
                max_retries = validate_max_retries(int(retries_str))
            except ValueError as exc:
                raise ValueError(
                    "PY_MOMO_SDK_MAX_RETRIES must be a non-negative integer"
                ) from exc
        else:
            max_retries = 0

        backoff_str = cls._env_stripped("PY_MOMO_SDK_RETRY_BACKOFF")
        if backoff_str:
            try:
                retry_backoff = validate_retry_backoff(float(backoff_str))
            except ValueError as exc:
                raise ValueError(
                    "PY_MOMO_SDK_RETRY_BACKOFF must be a positive finite number"
                ) from exc
        else:
            retry_backoff = 0.5

        collection = cls._product_from_env("PY_MOMO_SDK_COLLECTION", "collection")
        disbursement = cls._product_from_env("PY_MOMO_SDK_DISBURSEMENT", "disbursement")
        remittance = cls._product_from_env("PY_MOMO_SDK_REMITTANCE", "remittance")

        return cls(
            environment=env,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            collection=collection,
            disbursement=disbursement,
            remittance=remittance,
        )
