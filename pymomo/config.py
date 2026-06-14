from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

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
    callback_url: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"ProductConfig(api_user={self.api_user!r}, "
            f"api_key=<redacted>, subscription_key=<redacted>)"
        )


@dataclass
class MomoConfig:
    """Top-level configuration for a MomoClient instance."""

    environment: str = SANDBOX
    base_url: Optional[str] = None  # Override for testing
    timeout: float = 30.0
    collection: Optional[ProductConfig] = None
    disbursement: Optional[ProductConfig] = None
    remittance: Optional[ProductConfig] = None

    def __post_init__(self) -> None:
        if self.base_url is None:
            self.base_url = (
                SANDBOX_BASE_URL if self.environment == SANDBOX else PRODUCTION_BASE_URL
            )

    @classmethod
    def from_env(cls) -> MomoConfig:
        """Create a MomoConfig instance by reading environment variables.

        Returns:
            A MomoConfig instance populated with environment variable values.
        """
        env = os.environ.get("PYMOMO_ENVIRONMENT", SANDBOX)
        base_url = os.environ.get("PYMOMO_BASE_URL")
        timeout_str = os.environ.get("PYMOMO_TIMEOUT")
        timeout = float(timeout_str) if timeout_str else 30.0

        # Collection Config
        coll_sub = os.environ.get("PYMOMO_COLLECTION_SUBSCRIPTION_KEY")
        coll_user = os.environ.get("PYMOMO_COLLECTION_API_USER")
        coll_key = os.environ.get("PYMOMO_COLLECTION_API_KEY")
        coll_cb = os.environ.get("PYMOMO_COLLECTION_CALLBACK_URL")
        collection = None
        if coll_sub or coll_user or coll_key:
            collection = ProductConfig(
                subscription_key=coll_sub or "",
                api_user=coll_user or "",
                api_key=coll_key or "",
                callback_url=coll_cb,
            )

        # Disbursement Config
        disb_sub = os.environ.get("PYMOMO_DISBURSEMENT_SUBSCRIPTION_KEY")
        disb_user = os.environ.get("PYMOMO_DISBURSEMENT_API_USER")
        disb_key = os.environ.get("PYMOMO_DISBURSEMENT_API_KEY")
        disb_cb = os.environ.get("PYMOMO_DISBURSEMENT_CALLBACK_URL")
        disbursement = None
        if disb_sub or disb_user or disb_key:
            disbursement = ProductConfig(
                subscription_key=disb_sub or "",
                api_user=disb_user or "",
                api_key=disb_key or "",
                callback_url=disb_cb,
            )

        # Remittance Config
        rem_sub = os.environ.get("PYMOMO_REMITTANCE_SUBSCRIPTION_KEY")
        rem_user = os.environ.get("PYMOMO_REMITTANCE_API_USER")
        rem_key = os.environ.get("PYMOMO_REMITTANCE_API_KEY")
        rem_cb = os.environ.get("PYMOMO_REMITTANCE_CALLBACK_URL")
        remittance = None
        if rem_sub or rem_user or rem_key:
            remittance = ProductConfig(
                subscription_key=rem_sub or "",
                api_user=rem_user or "",
                api_key=rem_key or "",
                callback_url=rem_cb,
            )

        return cls(
            environment=env,
            base_url=base_url,
            timeout=timeout,
            collection=collection,
            disbursement=disbursement,
            remittance=remittance,
        )
