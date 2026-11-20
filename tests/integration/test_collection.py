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


def test_collection_path_parameter_validation_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Verify sync product methods reject path traversal and handle enums/emails."""
    from pymomo.models import AccountHolderIdType

    with pytest.raises(ValueError):
        client.collection.get_balance_for_currency("../../requesttopay")
    with pytest.raises(ValueError):
        client.collection.is_account_holder_active("../../../account/balance", "email")
    with pytest.raises(ValueError):
        client.collection.is_account_holder_active("256771234567", "../invalid")
    with pytest.raises(ValueError):
        client.collection.get_basic_user_info("../secret", "party_code")

    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/accountholder/msisdn/256771234567/active",
        json={"result": True},
        status_code=200,
    )
    assert (
        client.collection.is_account_holder_active(
            "+256-771-234-567", AccountHolderIdType.msisdn
        )
        is True
    )

    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/accountholder/email/user%40example.com/basicuserinfo",
        json={"sub": "email-user", "name": "Email User"},
        status_code=200,
    )
    user = client.collection.get_basic_user_info("user@example.com", "email")
    assert user.name == "Email User"


@pytest.mark.asyncio
async def test_collection_path_parameter_validation_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Verify async product methods reject path traversal and encode emails."""
    from pymomo.models import AccountHolderIdType

    with pytest.raises(ValueError):
        await async_client.collection.get_balance_for_currency("../balance")
    with pytest.raises(ValueError):
        await async_client.collection.is_account_holder_active(
            "../../../account/balance", "email"
        )
    with pytest.raises(ValueError):
        await async_client.collection.get_basic_user_info("../secret", "party_code")

    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/accountholder/msisdn/256771234567/active",
        json={"result": True},
        status_code=200,
    )
    assert (
        await async_client.collection.is_account_holder_active(
            "+256 771 234 567", AccountHolderIdType.msisdn
        )
        is True
    )


def test_collection_create_oauth2_token_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test exchanging a CIBA auth_req_id for an OAuth2 token synchronously."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/oauth2/token/",
        json={
            "access_token": "ciba-user-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "profile",
            "refresh_token": "ciba-refresh-token",
            "refresh_token_expired_in": 7200,
        },
        status_code=200,
    )

    token = client.collection.create_oauth2_token("auth-req-id-123")
    assert token.access_token == "ciba-user-access-token"
    assert token.token_type == "Bearer"
    assert token.expires_in == 3600
    assert token.scope == "profile"
    assert token.refresh_token == "ciba-refresh-token"
    assert token.refresh_token_expired_in == 7200

    req = httpx_mock.get_requests()[0]
    assert req.headers["Authorization"].startswith("Basic ")
    assert req.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert b"auth_req_id=auth-req-id-123" in req.read()

    with pytest.raises(ValueError, match="auth_req_id"):
        client.collection.create_oauth2_token("")
    with pytest.raises(ValueError, match="grant_type"):
        client.collection.create_oauth2_token("auth-req-id-123", grant_type="")


@pytest.mark.asyncio
async def test_collection_create_oauth2_token_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test exchanging a CIBA auth_req_id for an OAuth2 token asynchronously."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/oauth2/token/",
        json={
            "access_token": "ciba-async-token",
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": "profile",
        },
        status_code=200,
    )

    token = await async_client.collection.create_oauth2_token("auth-req-async-123")
    assert token.access_token == "ciba-async-token"
    assert token.expires_in == 1800

    with pytest.raises(ValueError, match="auth_req_id"):
        await async_client.collection.create_oauth2_token("   ")
    with pytest.raises(ValueError, match="grant_type"):
        await async_client.collection.create_oauth2_token(
            "auth-req-async-123", grant_type="   "
        )


def test_collection_bc_authorize_validation_and_bad_schema_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Verify bc_authorize input checks and schema-mismatch wrapping to PyMoMoError."""
    from pymomo.exceptions import PyMoMoError

    with pytest.raises(ValueError, match="login_hint"):
        client.collection.bc_authorize("   ")
    with pytest.raises(ValueError, match="scope"):
        client.collection.bc_authorize("256771234567", scope="")
    with pytest.raises(ValueError, match="access_type"):
        client.collection.bc_authorize("256771234567", access_type="bad\r\n")

    mock_token_response(httpx_mock)
    ref_id = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay/{ref_id}",
        json={"unexpected": "missing-status"},
        status_code=200,
    )
    with pytest.raises(PyMoMoError, match="TransactionResult schema"):
        client.collection.get_payment_status(ref_id)
