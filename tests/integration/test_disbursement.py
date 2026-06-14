from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from pymomo import AsyncMomoClient, MomoClient
from pymomo.models import TransactionStatus


def mock_token_response(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/token/",
        json={
            "access_token": "mock-disbursement-token",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )


def test_disbursement_transfer_sync(client: MomoClient, httpx_mock: HTTPXMock) -> None:
    """Test disbursement transfer synchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/transfer",
        status_code=202,
    )

    ref_id = client.disbursement.transfer(
        amount="150.00",
        currency="UGX",
        payee_msisdn="256771234567",
        external_id="ext-trans-1",
    )
    assert len(ref_id) == 36


@pytest.mark.asyncio
async def test_disbursement_transfer_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test disbursement transfer asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/transfer",
        status_code=202,
    )

    ref_id = await async_client.disbursement.transfer(
        amount="300.00",
        currency="UGX",
        payee_msisdn="256771234567",
        external_id="ext-trans-2",
    )
    assert len(ref_id) == 36


def test_disbursement_get_transfer_status_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting transfer status synchronously."""
    mock_token_response(httpx_mock)
    ref_id = "c38b25e7-a9a3-4874-9cb3-671e6268f760"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/transfer/{ref_id}",
        json={
            "financialTransactionId": "tx-123",
            "status": "SUCCESSFUL",
            "amount": "150.00",
            "currency": "UGX",
        },
        status_code=200,
    )

    result = client.disbursement.get_transfer_status(ref_id)
    assert result.status == TransactionStatus.successful
    assert result.financial_transaction_id == "tx-123"


def test_disbursement_deposit_sync(client: MomoClient, httpx_mock: HTTPXMock) -> None:
    """Test disbursement deposit synchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v2_0/deposit",
        status_code=202,
    )

    ref_id = client.disbursement.deposit(
        amount="250.00",
        currency="UGX",
        payee_msisdn="256771234567",
        external_id="ext-dep-1",
    )
    assert len(ref_id) == 36


def test_disbursement_refund_sync(client: MomoClient, httpx_mock: HTTPXMock) -> None:
    """Test disbursement refund synchronously."""
    mock_token_response(httpx_mock)
    ref_to_refund = "c38b25e7-a9a3-4874-9cb3-671e6268f760"
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v2_0/refund",
        status_code=202,
    )

    ref_id = client.disbursement.refund(
        amount="50.00",
        currency="UGX",
        reference_id_to_refund=ref_to_refund,
        external_id="ext-ref-1",
    )
    assert len(ref_id) == 36


def test_disbursement_get_balance_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting disbursement balance synchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/account/balance",
        json={"availableBalance": "20000", "currency": "UGX"},
        status_code=200,
    )

    balance = client.disbursement.get_balance()
    assert balance.available_balance == "20000"
    assert balance.currency == "UGX"


def test_disbursement_is_account_active_sync(
    client: MomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test checking if payee account is active synchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/accountholder/msisdn/256771234567/active",
        json={"result": True},
        status_code=200,
    )

    is_active = client.disbursement.is_account_holder_active("256771234567")
    assert is_active is True


@pytest.mark.asyncio
async def test_disbursement_get_transfer_status_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting transfer status asynchronously."""
    mock_token_response(httpx_mock)
    ref_id = "c38b25e7-a9a3-4874-9cb3-671e6268f760"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/transfer/{ref_id}",
        json={
            "financialTransactionId": "tx-async-123",
            "status": "SUCCESSFUL",
            "amount": "150.00",
            "currency": "UGX",
        },
        status_code=200,
    )

    result = await async_client.disbursement.get_transfer_status(ref_id)
    assert result.status == TransactionStatus.successful
    assert result.financial_transaction_id == "tx-async-123"


@pytest.mark.asyncio
async def test_disbursement_deposit_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test disbursement deposit asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v2_0/deposit",
        status_code=202,
    )

    ref_id = await async_client.disbursement.deposit(
        amount="250.00",
        currency="UGX",
        payee_msisdn="256771234567",
        external_id="ext-dep-async",
    )
    assert len(ref_id) == 36


@pytest.mark.asyncio
async def test_disbursement_get_deposit_status_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting deposit status asynchronously."""
    mock_token_response(httpx_mock)
    ref_id = "c38b25e7-a9a3-4874-9cb3-671e6268f760"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/disbursement/v2_0/deposit/{ref_id}",
        json={
            "financialTransactionId": "dep-async-123",
            "status": "SUCCESSFUL",
            "amount": "250.00",
            "currency": "UGX",
        },
        status_code=200,
    )

    result = await async_client.disbursement.get_deposit_status(ref_id)
    assert result.status == TransactionStatus.successful
    assert result.financial_transaction_id == "dep-async-123"


@pytest.mark.asyncio
async def test_disbursement_refund_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test disbursement refund asynchronously."""
    mock_token_response(httpx_mock)
    ref_to_refund = "c38b25e7-a9a3-4874-9cb3-671e6268f760"
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v2_0/refund",
        status_code=202,
    )

    ref_id = await async_client.disbursement.refund(
        amount="50.00",
        currency="UGX",
        reference_id_to_refund=ref_to_refund,
        external_id="ext-ref-async",
    )
    assert len(ref_id) == 36


@pytest.mark.asyncio
async def test_disbursement_get_refund_status_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting refund status asynchronously."""
    mock_token_response(httpx_mock)
    ref_id = "c38b25e7-a9a3-4874-9cb3-671e6268f760"
    httpx_mock.add_response(
        method="GET",
        url=f"https://sandbox.momodeveloper.mtn.com/disbursement/v2_0/refund/{ref_id}",
        json={
            "financialTransactionId": "ref-async-123",
            "status": "SUCCESSFUL",
            "amount": "50.00",
            "currency": "UGX",
        },
        status_code=200,
    )

    result = await async_client.disbursement.get_refund_status(ref_id)
    assert result.status == TransactionStatus.successful
    assert result.financial_transaction_id == "ref-async-123"


@pytest.mark.asyncio
async def test_disbursement_get_balance_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting disbursement balance asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/account/balance",
        json={"availableBalance": "35000", "currency": "UGX"},
        status_code=200,
    )

    balance = await async_client.disbursement.get_balance()
    assert balance.available_balance == "35000"
    assert balance.currency == "UGX"


@pytest.mark.asyncio
async def test_disbursement_is_account_active_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test checking if payee account is active asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/accountholder/msisdn/256771234567/active",
        json={"result": True},
        status_code=200,
    )

    is_active = await async_client.disbursement.is_account_holder_active("256771234567")
    assert is_active is True


@pytest.mark.asyncio
async def test_disbursement_get_basic_user_info_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test retrieving basic user info asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/accountholder/msisdn/256771234567/basicuserinfo",
        json={
            "sub": "disb-sub-1",
            "name": "Jane Disbursement",
        },
        status_code=200,
    )

    user = await async_client.disbursement.get_basic_user_info("256771234567")
    assert user.name == "Jane Disbursement"
    assert user.sub == "disb-sub-1"


@pytest.mark.asyncio
async def test_disbursement_get_balance_for_currency_async(
    async_client: AsyncMomoClient, httpx_mock: HTTPXMock
) -> None:
    """Test getting balance for specific currency asynchronously."""
    mock_token_response(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/account/balance/UGX",
        json={"availableBalance": "35000", "currency": "UGX"},
        status_code=200,
    )

    balance = await async_client.disbursement.get_balance_for_currency("UGX")
    assert balance.available_balance == "35000"
    assert balance.currency == "UGX"
