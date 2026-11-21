from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from py_momo_sdk import AsyncPyMomoSDK, PyMomoSDK


def test_sandbox_provision_sync(client: PyMomoSDK, httpx_mock: HTTPXMock) -> None:
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
    from py_momo_sdk import sandbox

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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
    from py_momo_sdk._async import sandbox as async_sandbox

    original_gen = async_sandbox.generate_reference_id
    async_sandbox.generate_reference_id = lambda: "c38b25e7-a9a3-4874-9cb3-671e6268f760"

    try:
        result = await async_client.sandbox.provision()
        assert result["api_user"] == "c38b25e7-a9a3-4874-9cb3-671e6268f760"
        assert result["api_key"] == "mocked-async-api-key"
    finally:
        async_sandbox.generate_reference_id = original_gen


def test_sandbox_get_api_user_sync(client: PyMomoSDK, httpx_mock: HTTPXMock) -> None:
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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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


def test_sandbox_provisioner_guards_and_redaction() -> None:
    """Verify SandboxProvisioner rejects production env, missing key/http, and redacts key."""
    from py_momo_sdk import AsyncSandboxProvisioner, SandboxProvisioner
    from py_momo_sdk.config import MTN_UGANDA, ProductConfig, PyMomoSDKConfig
    from py_momo_sdk.exceptions import MissingCredentialsError, PyMomoSDKError
    from py_momo_sdk.http import HttpClient

    http = HttpClient("https://sandbox.momodeveloper.mtn.com", 30.0)
    try:
        # Missing HTTP client
        with pytest.raises(PyMomoSDKError, match="HTTP client is required"):
            SandboxProvisioner(
                subscription_key="sub-key", config=PyMomoSDKConfig(), http=None
            )

        # Missing subscription key
        with pytest.raises(
            MissingCredentialsError, match="Subscription key is required"
        ):
            SandboxProvisioner(config=PyMomoSDKConfig(), http=http)

        # Non-sandbox environment rejected
        prod_config = PyMomoSDKConfig(
            environment=MTN_UGANDA,
            collection=ProductConfig(
                subscription_key="prod-sub-key",
                api_user="e4d6934c-6fa1-49b4-9c59-bf558661b17c",
                api_key="prod-api-key",
            ),
        )
        with pytest.raises(PyMomoSDKError, match="sandbox environment"):
            SandboxProvisioner(config=prod_config, http=http)

        # Subscription key redacted in repr/str
        provisioner = SandboxProvisioner(
            subscription_key="secret-sandbox-sub-key",
            config=PyMomoSDKConfig(),
            http=http,
        )
        assert "secret-sandbox-sub-key" not in repr(provisioner)
        assert "secret-sandbox-sub-key" not in str(provisioner)
        assert "subscription_key=<redacted>" in repr(provisioner)

        # Async guards
        with pytest.raises(PyMomoSDKError, match="HTTP client is required"):
            AsyncSandboxProvisioner(
                subscription_key="sub-key", config=PyMomoSDKConfig(), http=None
            )

        # Control chars / blank subscription_key & production base_url without config rejected
        with pytest.raises(MissingCredentialsError):
            SandboxProvisioner("   ", http)
        with pytest.raises(ValueError, match="control characters"):
            SandboxProvisioner("sub\r\nkey", http)
        prod_http = HttpClient("https://proxy.momoapi.mtn.com", 30.0)
        try:
            with pytest.raises(PyMomoSDKError, match="sandbox environment"):
                SandboxProvisioner("sub-key", prod_http)
        finally:
            prod_http.close()
    finally:
        http.close()


def test_create_sandbox_provisioner_sync(httpx_mock: HTTPXMock) -> None:
    """Test PyMomoSDK.create_sandbox_provisioner with an explicit subscription key."""
    from py_momo_sdk import PyMomoSDKConfig

    user_id = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/{user_id}",
        json={
            "providerCallbackHost": "https://callback.example.com",
            "targetEnvironment": "sandbox",
        },
        status_code=200,
    )

    with PyMomoSDK(PyMomoSDKConfig(environment="sandbox")) as bare_client:
        provisioner = bare_client.create_sandbox_provisioner("explicit-sub-key")
        info = provisioner.get_api_user(user_id)

    assert info.provider_callback_host == "https://callback.example.com"
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert requests[0].headers["Ocp-Apim-Subscription-Key"] == "explicit-sub-key"


@pytest.mark.asyncio
async def test_create_sandbox_provisioner_async(httpx_mock: HTTPXMock) -> None:
    """Test AsyncPyMomoSDK.create_sandbox_provisioner with an explicit subscription key."""
    from py_momo_sdk import PyMomoSDKConfig

    user_id = "c38b25e7-a9a3-4874-9cb3-671e6268f760"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/{user_id}",
        json={
            "providerCallbackHost": "https://async-callback.example.com",
            "targetEnvironment": "sandbox",
        },
        status_code=200,
    )

    async with AsyncPyMomoSDK(PyMomoSDKConfig(environment="sandbox")) as bare_client:
        provisioner = bare_client.create_sandbox_provisioner("explicit-async-key")
        info = await provisioner.get_api_user(user_id)

    assert info.provider_callback_host == "https://async-callback.example.com"
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert requests[0].headers["Ocp-Apim-Subscription-Key"] == "explicit-async-key"
