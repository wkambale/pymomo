from __future__ import annotations

from typing import AsyncGenerator

import pytest

from pymomo import AsyncMomoClient, MomoClient
from pymomo.config import SANDBOX, MomoConfig, ProductConfig


@pytest.fixture
def collection_config() -> ProductConfig:
    """Fixture for collection product credentials."""
    return ProductConfig(
        subscription_key="test-subscription-key",
        api_user="e4d6934c-6fa1-49b4-9c59-bf558661b17c",  # Valid UUID v4
        api_key="test-api-key",
        callback_url="https://example.com/callback",
    )


@pytest.fixture
def disbursement_config() -> ProductConfig:
    """Fixture for disbursement product credentials."""
    return ProductConfig(
        subscription_key="test-disbursement-sub-key",
        api_user="c38b25e7-a9a3-4874-9cb3-671e6268f760",  # Valid UUID v4
        api_key="test-disbursement-key",
        callback_url="https://example.com/callback",
    )


@pytest.fixture
def remittance_config() -> ProductConfig:
    """Fixture for remittance product credentials."""
    return ProductConfig(
        subscription_key="test-remittance-sub-key",
        api_user="fa0c1bf6-90e6-4bf4-be8d-194380eb9a34",  # Valid UUID v4
        api_key="test-remittance-key",
        callback_url="https://example.com/callback",
    )


@pytest.fixture
def momo_config(
    collection_config: ProductConfig,
    disbursement_config: ProductConfig,
    remittance_config: ProductConfig,
) -> MomoConfig:
    """Fixture for top-level MomoConfig containing all product configurations."""
    return MomoConfig(
        environment=SANDBOX,
        collection=collection_config,
        disbursement=disbursement_config,
        remittance=remittance_config,
    )


@pytest.fixture
def client(momo_config: MomoConfig) -> MomoClient:
    """Fixture for a configured synchronous MomoClient."""
    return MomoClient(momo_config)


@pytest.fixture
async def async_client(
    momo_config: MomoConfig,
) -> AsyncGenerator[AsyncMomoClient, None]:
    """Fixture for a configured asynchronous AsyncMomoClient."""
    async with AsyncMomoClient(momo_config) as client:
        yield client
