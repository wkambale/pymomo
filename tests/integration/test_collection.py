from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock

from py_momo_sdk import AsyncPyMomoSDK, PyMomoSDK
from py_momo_sdk.exceptions import AuthenticationError
from py_momo_sdk.models import TransactionStatus


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


def test_collection_get_balance_sync(client: PyMomoSDK, httpx_mock: HTTPXMock) -> None:
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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
    client: PyMomoSDK, httpx_mock: HTTPXMock
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
        payer_msisdn="+256 771-234-567",
        external_id="ext-pay-1",
        payer_message="Pay msg",
        payee_note="Pay note",
    )
    assert len(ref_id) == 36  # UUID length
    req = next(
        r
        for r in httpx_mock.get_requests()
        if r.url.path == "/collection/v1_0/requesttopay"
    )
    assert req.headers["X-Reference-Id"] == ref_id
    assert req.headers["X-Callback-Url"] == "https://example.com/callback"
    assert req.headers["Ocp-Apim-Subscription-Key"] == "test-subscription-key"
    assert req.headers["X-Target-Environment"] == "sandbox"
    assert req.headers["Authorization"] == "Bearer mock-access-token-123"
    assert json.loads(req.read().decode("utf-8")) == {
        "amount": "100.00",
        "currency": "UGX",
        "externalId": "ext-pay-1",
        "payer": {"partyIdType": "MSISDN", "partyId": "256771234567"},
        "payerMessage": "Pay msg",
        "payeeNote": "Pay note",
    }


@pytest.mark.asyncio
async def test_collection_request_to_pay_async(
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
        payer_msisdn="+256-771-234-567",
        external_id="ext-pay-2",
    )
    assert len(ref_id) == 36
    req = next(
        r
        for r in httpx_mock.get_requests()
        if r.url.path == "/collection/v1_0/requesttopay"
    )
    assert req.headers["X-Reference-Id"] == ref_id
    assert req.headers["X-Callback-Url"] == "https://example.com/callback"
    assert req.headers["Ocp-Apim-Subscription-Key"] == "test-subscription-key"
    assert req.headers["X-Target-Environment"] == "sandbox"
    assert req.headers["Authorization"] == "Bearer mock-access-token-123"
    sent = json.loads(req.read().decode("utf-8"))
    assert sent["externalId"] == "ext-pay-2"
    assert sent["payer"] == {"partyIdType": "MSISDN", "partyId": "256771234567"}


def test_collection_get_payment_status_sync(
    client: PyMomoSDK, httpx_mock: HTTPXMock
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


def test_collection_401_retry_sync(client: PyMomoSDK, httpx_mock: HTTPXMock) -> None:
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
    bal_reqs = [
        r
        for r in httpx_mock.get_requests()
        if r.url.path == "/collection/v1_0/account/balance"
    ]
    assert [r.headers["Authorization"] for r in bal_reqs] == [
        "Bearer mock-access-token-123",
        "Bearer new-access-token-456",
    ]


def test_collection_401_fails_twice_sync(
    client: PyMomoSDK, httpx_mock: HTTPXMock
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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
    bal_reqs = [
        r
        for r in httpx_mock.get_requests()
        if r.url.path == "/collection/v1_0/account/balance"
    ]
    assert [r.headers["Authorization"] for r in bal_reqs] == [
        "Bearer mock-access-token-123",
        "Bearer new-access-token-async-456",
    ]


@pytest.mark.asyncio
async def test_collection_401_fails_twice_async(
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
    client: PyMomoSDK, httpx_mock: HTTPXMock
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
        payer_msisdn="+256 771-234-567",
        external_id="ext-with-1",
    )
    assert len(ref_id) == 36
    req = next(
        r
        for r in httpx_mock.get_requests()
        if r.url.path == "/collection/v2_0/requesttowithdraw"
    )
    assert req.headers["X-Reference-Id"] == ref_id
    assert req.headers["X-Callback-Url"] == "https://example.com/callback"
    assert req.headers["Ocp-Apim-Subscription-Key"] == "test-subscription-key"
    assert req.headers["X-Target-Environment"] == "sandbox"
    assert req.headers["Authorization"] == "Bearer mock-access-token-123"
    sent = json.loads(req.read().decode("utf-8"))
    assert sent["externalId"] == "ext-with-1"
    assert sent["payer"] == {"partyIdType": "MSISDN", "partyId": "256771234567"}


def test_collection_bc_authorize_sync(client: PyMomoSDK, httpx_mock: HTTPXMock) -> None:
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
    client: PyMomoSDK, httpx_mock: HTTPXMock
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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
        payer_msisdn="+256 771-234-567",
        external_id="ext-with-2",
    )
    assert len(ref_id) == 36
    req = next(
        r
        for r in httpx_mock.get_requests()
        if r.url.path == "/collection/v2_0/requesttowithdraw"
    )
    assert req.headers["X-Reference-Id"] == ref_id
    assert req.headers["X-Callback-Url"] == "https://example.com/callback"
    assert req.headers["Ocp-Apim-Subscription-Key"] == "test-subscription-key"
    assert json.loads(req.read().decode("utf-8"))["payer"]["partyId"] == "256771234567"


@pytest.mark.asyncio
async def test_collection_get_withdraw_status_async(
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
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
    client: PyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Verify sync product methods reject path traversal and handle enums/emails."""
    from py_momo_sdk.models import AccountHolderIdType

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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Verify async product methods reject path traversal and encode emails."""
    from py_momo_sdk.models import AccountHolderIdType

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
    client: PyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Test exchanging a CIBA auth_req_id for an OAuth2 token synchronously."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/oauth2/token/",
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
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Test exchanging a CIBA auth_req_id for an OAuth2 token asynchronously."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/oauth2/token/",
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
    client: PyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Verify bc_authorize input checks and schema-mismatch wrapping to PyMomoSDKError."""
    from py_momo_sdk.exceptions import PyMomoSDKError

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
    with pytest.raises(PyMomoSDKError, match="TransactionResult schema"):
        client.collection.get_payment_status(ref_id)


@pytest.mark.asyncio
async def test_collection_concurrent_async_calls_fetch_token_once(
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Verify concurrent async calls on a cold cache fetch only one OAuth token."""
    import asyncio

    mock_token_response(httpx_mock)
    for _ in range(5):
        httpx_mock.add_response(
            method="GET",
            url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
            json={"availableBalance": "1000", "currency": "UGX"},
            status_code=200,
        )

    results = await asyncio.gather(
        *(async_client.collection.get_balance() for _ in range(5))
    )
    assert len(results) == 5
    token_reqs = [
        r for r in httpx_mock.get_requests() if r.url.path == "/collection/token/"
    ]
    assert len(token_reqs) == 1


def test_collection_malformed_token_response_raises_auth_error(
    client: PyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Verify empty access_token or non-positive expires_in raises AuthenticationError."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={"access_token": "", "token_type": "access_token", "expires_in": 3600},
        status_code=200,
    )
    with pytest.raises(AuthenticationError, match="Invalid token response"):
        client.collection.get_balance()


@pytest.mark.asyncio
async def test_issue_130_mtn_ciba_userinfo_delivery_notification_and_preapproval(
    client: PyMomoSDK, async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Verify Issue #130: One API URL, consented userinfo, delivery notification, and PreApproval."""
    from py_momo_sdk import (
        MTN_UGANDA,
        ONE_API_PRODUCTION_BASE_URL,
        PyMomoSDKConfig,
    )

    assert ONE_API_PRODUCTION_BASE_URL == "https://momoapi.momo.africa"
    one_api_cfg = PyMomoSDKConfig(
        environment=MTN_UGANDA, base_url=ONE_API_PRODUCTION_BASE_URL
    )
    assert one_api_cfg.base_url == "https://momoapi.momo.africa"

    # 1. Consented userinfo (sync + async) via GET /collection/oauth2/v1_0/userinfo
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/oauth2/v1_0/userinfo",
        json={"sub": "sub-130", "name": "Consented User", "locale": "en_UG"},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/oauth2/v1_0/userinfo",
        json={"sub": "sub-130-async", "name": "Async Consented User"},
        status_code=200,
    )
    info = client.collection.get_user_info_with_consent("user-consent-bearer-token")
    assert info.name == "Consented User"
    ainfo = await async_client.collection.get_user_info_with_consent(
        "async-consent-bearer-token"
    )
    assert ainfo.sub == "sub-130-async"
    with pytest.raises(ValueError, match="oauth2_access_token"):
        client.collection.get_user_info_with_consent("   ")

    # 2. Delivery notification (sync + async)
    ref_id = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    mock_token_response(httpx_mock)
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay/{ref_id}/deliverynotification",
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay/{ref_id}/deliverynotification",
        status_code=200,
    )
    client.collection.send_delivery_notification(
        ref_id, "Payment received", language="en"
    )
    await async_client.collection.send_delivery_notification(
        ref_id, "Payment received async", language="fr"
    )
    with pytest.raises(ValueError, match="language"):
        client.collection.send_delivery_notification(ref_id, "Hi", language="english")

    # 3. PreApproval create / status / cancel (sync + async)
    pre_ref = "11111111-2222-4333-8444-555555555555"
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v2_0/preapproval",
        status_code=202,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v2_0/preapproval/{pre_ref}",
        json={
            "payerCurrency": "UGX",
            "validityTime": 3600,
            "status": "APPROVED",
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="DELETE",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v2_0/preapproval/{pre_ref}",
        status_code=200,
    )
    created_ref = client.collection.create_preapproval(
        payer_msisdn="+256771234567",
        payer_currency="UGX",
        validity_time=3600,
        payer_message="Monthly subscription",
        reference_id=pre_ref,
    )
    assert created_ref == pre_ref
    pre_status = client.collection.get_preapproval_status(pre_ref)
    assert pre_status.is_approved() is True
    assert pre_status.is_pending() is False
    assert pre_status.is_failed() is False
    client.collection.cancel_preapproval(pre_ref)

    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v2_0/preapproval",
        status_code=202,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v2_0/preapproval/{pre_ref}",
        json={
            "status": "FAILED",
            "reason": {"code": "APPROVAL_REJECTED", "message": "User declined"},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="DELETE",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v2_0/preapproval/{pre_ref}",
        status_code=200,
    )
    assert (
        await async_client.collection.create_preapproval(
            payer_msisdn="256771234567",
            payer_currency="UGX",
            validity_time=1800,
            reference_id=pre_ref,
        )
        == pre_ref
    )
    apre_status = await async_client.collection.get_preapproval_status(pre_ref)
    assert apre_status.is_failed() is True
    assert apre_status.reason_code == "APPROVAL_REJECTED"
    await async_client.collection.cancel_preapproval(pre_ref)


@pytest.mark.asyncio
async def test_issue_166_mtn_utf8_delivery_notification_preapproval_strip_and_liberia_usd(
    client: PyMomoSDK, async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Verify Issue #166: French UTF-8 deliverynotification, PreApproval stripping, and MTN Liberia USD."""
    import json

    from py_momo_sdk import MtnMomoProvider, PaymentRequest, PaymentRouter

    ref_id = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    mock_token_response(httpx_mock)
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay/{ref_id}/deliverynotification",
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay/{ref_id}/deliverynotification",
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v2_0/preapproval",
        status_code=202,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v2_0/preapproval",
        status_code=202,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay",
        status_code=202,
    )

    french_msg = "Paiement reçu avec succès"
    client.collection.send_delivery_notification(ref_id, french_msg, language="fr")
    await async_client.collection.send_delivery_notification(
        ref_id, french_msg, language="fr"
    )

    # PreApproval strips party_id_type and non-MSISDN payer_msisdn
    client.collection.create_preapproval(
        payer_msisdn="  buyer@example.com  ",
        payer_currency="EUR",
        validity_time=3600,
        party_id_type="  email  ",
        reference_id=ref_id,
    )
    await async_client.collection.create_preapproval(
        payer_msisdn="  PARTY123  ",
        payer_currency="EUR",
        validity_time=3600,
        party_id_type="  party_code  ",
        reference_id=ref_id,
    )

    # MTN Liberia (23188) USD routing
    router = PaymentRouter([MtnMomoProvider(client)])
    lr_res = router.collect(
        PaymentRequest(amount="15.00", currency="USD", payer_msisdn="231881234567")
    )
    assert lr_res.provider == "mtn_momo"

    dn_reqs = [
        r
        for r in httpx_mock.get_requests()
        if r.url.path.endswith("/deliverynotification")
    ]
    assert len(dn_reqs) == 2
    for r in dn_reqs:
        assert "notificationMessage" not in r.headers
        assert r.headers["Language"] == "fr"
        assert json.loads(r.read().decode("utf-8")) == {
            "notificationMessage": french_msg
        }

    pre_reqs = [
        r
        for r in httpx_mock.get_requests()
        if r.url.path == "/collection/v2_0/preapproval"
    ]
    assert json.loads(pre_reqs[0].read().decode("utf-8"))["payer"] == {
        "partyIdType": "EMAIL",
        "partyId": "buyer@example.com",
    }
    assert json.loads(pre_reqs[1].read().decode("utf-8"))["payer"] == {
        "partyIdType": "PARTY_CODE",
        "partyId": "PARTY123",
    }
