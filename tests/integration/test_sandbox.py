from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from pymomo import AsyncMomoClient, MomoClient


def test_sandbox_provision_sync(client: MomoClient, httpx_mock: HTTPXMock) -> None:
    """Test sandbox provisioning synchronously."""
    # Mock create_api_user POST
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/v1_0/apiuser",
        status_code=201,
    )

    # Mock create_api_key POST
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/e4d6934c-6fa1-49b4-9c59-bf558661b17c/apikey",
        json={"apiKey": "mocked-sandbox-api-key"},
        status_code=201,
    )

    # We patch generate_reference_id to return a predictable user ID for testing
    from pymomo import sandbox

    original_gen = sandbox.generate_reference_id
    sandbox.generate_reference_id = lambda: "e4d6934c-6fa1-49b4-9c59-bf558661b17c"

    try:
        # Run sync provision
        result = client.sandbox.provision()
        assert result["api_user"] == "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
        assert result["api_key"] == "mocked-sandbox-api-key"
    finally:
        sandbox.generate_reference_id = original_gen


@pytest.mark.asyncio
async def test_sandbox_provision_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test sandbox provisioning asynchronously."""
    # Mock create_api_user POST
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/v1_0/apiuser",
        status_code=201,
    )

    # Mock create_api_key POST
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/c38b25e7-a9a3-4874-9cb3-671e6268f760/apikey",
        json={"apiKey": "mocked-async-api-key"},
        status_code=201,
    )

    # Patch generate_reference_id for async_sandbox
    from pymomo._async import sandbox as async_sandbox

    original_gen = async_sandbox.generate_reference_id
    async_sandbox.generate_reference_id = lambda: "c38b25e7-a9a3-4874-9cb3-671e6268f760"

    try:
        result = await async_client.sandbox.provision()
        assert result["api_user"] == "c38b25e7-a9a3-4874-9cb3-671e6268f760"
        assert result["api_key"] == "mocked-async-api-key"
    finally:
        async_sandbox.generate_reference_id = original_gen


def test_sandbox_get_api_user_sync(client: MomoClient, httpx_mock: HTTPXMock) -> None:
    """Test getting API user information synchronously."""
    user_id = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/{user_id}",
        json={
            "providerCallbackHost": "https://callback.com",
            "targetEnvironment": "sandbox",
        },
        status_code=200,
    )

    info = client.sandbox.get_api_user(user_id)
    assert info.provider_callback_host == "https://callback.com"
    assert info.target_environment == "sandbox"


@pytest.mark.asyncio
async def test_sandbox_get_api_user_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting API user information asynchronously."""
    user_id = "c38b25e7-a9a3-4874-9cb3-671e6268f760"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/{user_id}",
        json={
            "providerCallbackHost": "https://async-callback.com",
            "targetEnvironment": "sandbox",
        },
        status_code=200,
    )

    info = await async_client.sandbox.get_api_user(user_id)
    assert info.provider_callback_host == "https://async-callback.com"
    assert info.target_environment == "sandbox"
