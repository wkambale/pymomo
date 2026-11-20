from __future__ import annotations

import os
from dataclasses import dataclass

from py_momo_sdk.exceptions import MissingCredentialsError
from py_momo_sdk.telemetry import TelemetryHook
from py_momo_sdk.utils import (
    validate_callback_url,
    validate_environment_name,
    validate_header_value,
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

SANDBOX_BASE_URL = "https://sandbox.momodeveloper.mtn.com"
PRODUCTION_BASE_URL = "https://proxy.momoapi.mtn.com"


@dataclass
class ProductConfig:
    """Credentials and settings for a single MoMo product."""

    subscription_key: str
    api_user: str
    api_key: str
    callback_url: str | None = None

    def __post_init__(self) -> None:
        validate_header_value(self.subscription_key, field_name="subscription_key")
        validate_header_value(self.api_user, field_name="api_user")
        validate_header_value(self.api_key, field_name="api_key")
        if self.callback_url is not None:
            validate_callback_url(self.callback_url)

    def __repr__(self) -> str:
        return (
            f"ProductConfig(api_user={self.api_user!r}, "
            f"api_key=<redacted>, subscription_key=<redacted>)"
        )


@dataclass
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
        self.timeout = validate_timeout(self.timeout)
        if isinstance(self.max_retries, bool) or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if (
            isinstance(self.retry_backoff, bool)
            or self.retry_backoff <= 0
            or self.retry_backoff != self.retry_backoff
        ):
            raise ValueError("retry_backoff must be a positive finite number")
        if self.base_url is None:
            self.base_url = (
                SANDBOX_BASE_URL if self.environment == SANDBOX else PRODUCTION_BASE_URL
            )

    @staticmethod
    def _product_from_env(prefix: str, product_label: str) -> ProductConfig | None:
        sub = os.environ.get(f"{prefix}_SUBSCRIPTION_KEY")
        user = os.environ.get(f"{prefix}_API_USER")
        key = os.environ.get(f"{prefix}_API_KEY")
        cb = os.environ.get(f"{prefix}_CALLBACK_URL")
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

        Returns:
            A PyMomoSDKConfig instance populated with environment variable values.

        Raises:
            ValueError: If ``PY_MOMO_SDK_TIMEOUT`` is not a positive finite number.
            MissingCredentialsError: If a product is only partially configured.
        """
        env = os.environ.get("PY_MOMO_SDK_ENVIRONMENT", SANDBOX)
        base_url = os.environ.get("PY_MOMO_SDK_BASE_URL")
        timeout_str = os.environ.get("PY_MOMO_SDK_TIMEOUT")
        if timeout_str:
            try:
                timeout = validate_timeout(float(timeout_str))
            except ValueError as exc:
                raise ValueError(
                    "PY_MOMO_SDK_TIMEOUT must be a positive finite number"
                ) from exc
        else:
            timeout = 30.0

        collection = cls._product_from_env("PY_MOMO_SDK_COLLECTION", "collection")
        disbursement = cls._product_from_env("PY_MOMO_SDK_DISBURSEMENT", "disbursement")
        remittance = cls._product_from_env("PY_MOMO_SDK_REMITTANCE", "remittance")

        return cls(
            environment=env,
            base_url=base_url,
            timeout=timeout,
            collection=collection,
            disbursement=disbursement,
            remittance=remittance,
        )
