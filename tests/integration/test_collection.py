from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from pymomo import AsyncMomoClient, MomoClient
from pymomo.exceptions import AuthenticationError
from pymomo.models import TransactionStatus


# Helper to mock token endpoint responses
def mock_token_response(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "mock-access-token-123",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )


def test_collection_get_balance_sync(client: MomoClient, httpx_mock: HTTPXMock) -> None:
    """Test getting collection balance synchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        json={"availableBalance": "5000", "currency": "UGX"},
        status_code=200,
    )

    balance = client.collection.get_balance()
    assert balance.available_balance == "5000"
    assert balance.currency == "UGX"


@pytest.mark.asyncio
async def test_collection_get_balance_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting collection balance asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        json={"availableBalance": "12000", "currency": "UGX"},
        status_code=200,
    )

    balance = await async_client.collection.get_balance()
    assert balance.available_balance == "12000"
    assert balance.currency == "UGX"


def test_collection_request_to_pay_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test request to pay synchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay",
        status_code=202,
    )

    ref_id = client.collection.request_to_pay(
        amount="100.00",
        currency="UGX",
        payer_msisdn="256771234567",
        external_id="ext-pay-1",
    )
    assert len(ref_id) == 36  # UUID length


@pytest.mark.asyncio
async def test_collection_request_to_pay_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test request to pay asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay",
        status_code=202,
    )

    ref_id = await async_client.collection.request_to_pay(
        amount="200.00",
        currency="UGX",
        payer_msisdn="256771234567",
        external_id="ext-pay-2",
    )
    assert len(ref_id) == 36


def test_collection_get_payment_status_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting payment status synchronously."""
    mock_token_response(httpx_mock)
    ref_id = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay/{ref_id}",
        json={
            "financialTransactionId": "tx-999",
            "status": "SUCCESSFUL",
            "amount": "100.00",
            "currency": "UGX",
        },
        status_code=200,
    )

    result = client.collection.get_payment_status(ref_id)
    assert result.status == TransactionStatus.successful
    assert result.financial_transaction_id == "tx-999"


def test_collection_401_retry_sync(client: MomoClient, httpx_mock: HTTPXMock) -> None:
    """Test that a 401 automatically refreshes token and retries request."""
    # First token fetch
    mock_token_response(httpx_mock)

    # Initial request gets 401
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        status_code=401,
    )

    # Secondary token fetch (triggered by 401 invalidation)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "new-access-token-456",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )

    # Retried request succeeds
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        json={"availableBalance": "3000", "currency": "UGX"},
        status_code=200,
    )

    balance = client.collection.get_balance()
    assert balance.available_balance == "3000"


def test_collection_401_fails_twice_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test that if retry also returns 401, AuthenticationError is raised."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        status_code=401,
    )
    mock_token_response(httpx_mock)  # Token refresh succeeds
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        status_code=401,  # Retry fails again
    )

    with pytest.raises(AuthenticationError):
        client.collection.get_balance()


@pytest.mark.asyncio
async def test_collection_401_retry_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test that a 401 automatically refreshes token and retries request asynchronously."""
    # First token fetch
    mock_token_response(httpx_mock)

    # Initial request gets 401
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        status_code=401,
    )

    # Secondary token fetch (triggered by 401 invalidation)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "new-access-token-async-456",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )

    # Retried request succeeds
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        json={"availableBalance": "3000", "currency": "UGX"},
        status_code=200,
    )

    balance = await async_client.collection.get_balance()
    assert balance.available_balance == "3000"


@pytest.mark.asyncio
async def test_collection_401_fails_twice_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test that if retry also returns 401, AuthenticationError is raised asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        status_code=401,
    )
    mock_token_response(httpx_mock)  # Token refresh succeeds
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        status_code=401,  # Retry fails again
    )

    with pytest.raises(AuthenticationError):
        await async_client.collection.get_balance()


def test_collection_request_to_withdraw_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test request to withdraw synchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v2_0/requesttowithdraw",
        status_code=202,
    )

    ref_id = client.collection.request_to_withdraw(
        amount="50.00",
        currency="UGX",
        payer_msisdn="256771234567",
        external_id="ext-with-1",
    )
    assert len(ref_id) == 36


def test_collection_bc_authorize_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test CIBA backchannel authorization synchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/bc-authorize",
        json={
            "auth_req_id": "auth-req-id-uuid",
            "expires_in": 600,
            "interval": 5,
        },
        status_code=200,
    )

    response = client.collection.bc_authorize(
        login_hint="256771234567",
        scope="profile",
    )
    assert response.auth_req_id == "auth-req-id-uuid"
    assert response.expires_in == 600
    assert response.interval == 5


def test_collection_get_basic_user_info_by_reference_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test retrieving user info by reference ID synchronously."""
    mock_token_response(httpx_mock)
    ref_id = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v2_0/user/{ref_id}/basicuserinfo",
        json={
            "sub": "user-sub",
            "name": "John Doe",
            "given_name": "John",
            "family_name": "Doe",
        },
        status_code=200,
    )

    user = client.collection.get_basic_user_info_by_reference(ref_id)
    assert user.name == "John Doe"
    assert user.sub == "user-sub"


@pytest.mark.asyncio
async def test_collection_get_payment_status_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting payment status asynchronously."""
    mock_token_response(httpx_mock)
    ref_id = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay/{ref_id}",
        json={
            "financialTransactionId": "tx-async-999",
            "status": "SUCCESSFUL",
            "amount": "200.00",
            "currency": "UGX",
        },
        status_code=200,
    )

    result = await async_client.collection.get_payment_status(ref_id)
    assert result.status == TransactionStatus.successful
    assert result.financial_transaction_id == "tx-async-999"


@pytest.mark.asyncio
async def test_collection_request_to_withdraw_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test request to withdraw asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v2_0/requesttowithdraw",
        status_code=202,
    )

    ref_id = await async_client.collection.request_to_withdraw(
        amount="75.00",
        currency="UGX",
        payer_msisdn="256771234567",
        external_id="ext-with-2",
    )
    assert len(ref_id) == 36


@pytest.mark.asyncio
async def test_collection_get_withdraw_status_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting withdraw status asynchronously."""
    mock_token_response(httpx_mock)
    ref_id = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v2_0/requesttowithdraw/{ref_id}",
        json={
            "financialTransactionId": "tx-with-async-999",
            "status": "SUCCESSFUL",
            "amount": "75.00",
            "currency": "UGX",
        },
        status_code=200,
    )

    result = await async_client.collection.get_withdraw_status(ref_id)
    assert result.status == TransactionStatus.successful
    assert result.financial_transaction_id == "tx-with-async-999"


@pytest.mark.asyncio
async def test_collection_bc_authorize_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test CIBA backchannel authorization asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/bc-authorize",
        json={
            "auth_req_id": "auth-req-async-uuid",
            "expires_in": 300,
            "interval": 5,
        },
        status_code=200,
    )

    response = await async_client.collection.bc_authorize(
        login_hint="256771234567",
        scope="profile",
    )
    assert response.auth_req_id == "auth-req-async-uuid"
    assert response.expires_in == 300


@pytest.mark.asyncio
async def test_collection_get_basic_user_info_by_reference_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test retrieving user info by reference ID asynchronously."""
    mock_token_response(httpx_mock)
    ref_id = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v2_0/user/{ref_id}/basicuserinfo",
        json={
            "sub": "user-sub-async",
            "name": "Jane Doe",
        },
        status_code=200,
    )

    user = await async_client.collection.get_basic_user_info_by_reference(ref_id)
    assert user.name == "Jane Doe"
    assert user.sub == "user-sub-async"


@pytest.mark.asyncio
async def test_collection_is_account_holder_active_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test checking active account holder asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/accountholder/msisdn/256771234567/active",
        json={"result": "true"},
        status_code=200,
    )

    is_active = await async_client.collection.is_account_holder_active("256771234567")
    assert is_active is True


@pytest.mark.asyncio
async def test_collection_get_basic_user_info_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test retrieving basic user info asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/accountholder/msisdn/256771234567/basicuserinfo",
        json={
            "sub": "user-sub-1",
            "name": "Alice Smith",
        },
        status_code=200,
    )

    user = await async_client.collection.get_basic_user_info("256771234567")
    assert user.name == "Alice Smith"
    assert user.sub == "user-sub-1"


@pytest.mark.asyncio
async def test_collection_get_balance_for_currency_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test retrieving balance for specific currency asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance/UGX",
        json={"availableBalance": "7500", "currency": "UGX"},
        status_code=200,
    )

    balance = await async_client.collection.get_balance_for_currency("UGX")
    assert balance.available_balance == "7500"
    assert balance.currency == "UGX"
