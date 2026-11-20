from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from py_momo_sdk import AsyncPyMomoSDK, PyMomoSDK
from py_momo_sdk.models import TransactionStatus


def mock_token_response(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/remittance/token/",
        json={
            "access_token": "mock-remittance-token",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )


def test_remittance_transfer_sync(client: PyMomoSDK, httpx_mock: HTTPXMock) -> None:
    """Test remittance transfer synchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/remittance/v1_0/transfer",
        status_code=202,
    )

    ref_id = client.remittance.transfer(
        amount="180.00",
        currency="UGX",
        payee_msisdn="256771234567",
        external_id="ext-rem-1",
    )
    assert len(ref_id) == 36


@pytest.mark.asyncio
async def test_remittance_transfer_async(
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Test remittance transfer asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/remittance/v1_0/transfer",
        status_code=202,
    )

    ref_id = await async_client.remittance.transfer(
        amount="360.00",
        currency="UGX",
        payee_msisdn="256771234567",
        external_id="ext-rem-2",
    )
    assert len(ref_id) == 36


def test_remittance_get_transfer_status_sync(
    client: PyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Test getting transfer status synchronously."""
    mock_token_response(httpx_mock)
    ref_id = "fa0c1bf6-90e6-4bf4-be8d-194380eb9a34"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/remittance/v1_0/transfer/{ref_id}",
        json={
            "financialTransactionId": "tx-rem-123",
            "status": "SUCCESSFUL",
            "amount": "180.00",
            "currency": "UGX",
        },
        status_code=200,
    )

    result = client.remittance.get_transfer_status(ref_id)
    assert result.status == TransactionStatus.successful
    assert result.financial_transaction_id == "tx-rem-123"


def test_remittance_get_balance_sync(client: PyMomoSDK, httpx_mock: HTTPXMock) -> None:
    """Test getting remittance balance synchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/remittance/v1_0/account/balance",
        json={"availableBalance": "30000", "currency": "UGX"},
        status_code=200,
    )

    balance = client.remittance.get_balance()
    assert balance.available_balance == "30000"
    assert balance.currency == "UGX"


@pytest.mark.asyncio
async def test_remittance_get_transfer_status_async(
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Test getting transfer status asynchronously."""
    mock_token_response(httpx_mock)
    ref_id = "fa0c1bf6-90e6-4bf4-be8d-194380eb9a34"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/remittance/v1_0/transfer/{ref_id}",
        json={
            "financialTransactionId": "tx-rem-async",
            "status": "SUCCESSFUL",
            "amount": "360.00",
            "currency": "UGX",
        },
        status_code=200,
    )

    result = await async_client.remittance.get_transfer_status(ref_id)
    assert result.status == TransactionStatus.successful
    assert result.financial_transaction_id == "tx-rem-async"


@pytest.mark.asyncio
async def test_remittance_get_balance_async(
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Test getting remittance balance asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/remittance/v1_0/account/balance",
        json={"availableBalance": "40000", "currency": "UGX"},
        status_code=200,
    )

    balance = await async_client.remittance.get_balance()
    assert balance.available_balance == "40000"
    assert balance.currency == "UGX"


@pytest.mark.asyncio
async def test_remittance_is_account_active_async(
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Test checking if payee account is active asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/remittance/v1_0/accountholder/msisdn/256771234567/active",
        json={"result": True},
        status_code=200,
    )

    is_active = await async_client.remittance.is_account_holder_active("256771234567")
    assert is_active is True


@pytest.mark.asyncio
async def test_remittance_get_basic_user_info_async(
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Test retrieving basic user info asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/remittance/v1_0/accountholder/msisdn/256771234567/basicuserinfo",
        json={
            "sub": "rem-sub-1",
            "name": "John Remittance",
        },
        status_code=200,
    )

    user = await async_client.remittance.get_basic_user_info("256771234567")
    assert user.name == "John Remittance"
    assert user.sub == "rem-sub-1"


@pytest.mark.asyncio
async def test_remittance_get_balance_for_currency_async(
    async_client: AsyncPyMomoSDK, httpx_mock: HTTPXMock
) -> None:
    """Test getting balance for specific currency asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/remittance/v1_0/account/balance/UGX",
        json={"availableBalance": "40000", "currency": "UGX"},
        status_code=200,
    )

    balance = await async_client.remittance.get_balance_for_currency("UGX")
    assert balance.available_balance == "40000"
    assert balance.currency == "UGX"
