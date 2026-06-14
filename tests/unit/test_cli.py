from __future__ import annotations

import json
from unittest.mock import patch

from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from pymomo._cli import app

runner = CliRunner()


def test_cli_sandbox_provision(httpx_mock: HTTPXMock) -> None:
    """Test CLI sandbox provision command."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/v1_0/apiuser",
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/e4d6934c-6fa1-49b4-9c59-bf558661b17c/apikey",
        json={"apiKey": "mocked-sandbox-api-key"},
        status_code=201,
    )

    with patch(
        "pymomo.sandbox.generate_reference_id",
        return_value="e4d6934c-6fa1-49b4-9c59-bf558661b17c",
    ):
        result = runner.invoke(
            app,
            [
                "sandbox",
                "provision",
                "--subscription-key",
                "test-sub-key",
                "--callback-host",
                "https://pymomo.aiforuganda.org",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["api_user"] == "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
        assert data["api_key"] == "mocked-sandbox-api-key"


def test_cli_sandbox_get_user(httpx_mock: HTTPXMock) -> None:
    """Test CLI sandbox get-user command."""
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

    result = runner.invoke(
        app,
        [
            "sandbox",
            "get-user",
            user_id,
            "--subscription-key",
            "test-sub-key",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["providerCallbackHost"] == "https://callback.com"
    assert data["targetEnvironment"] == "sandbox"


def test_cli_collection_balance(httpx_mock: HTTPXMock) -> None:
    """Test CLI collection balance command."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "token",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        json={"availableBalance": "250.00", "currency": "EUR"},
        status_code=200,
    )

    result = runner.invoke(
        app,
        [
            "collection",
            "balance",
            "--subscription-key",
            "key",
            "--api-user",
            "e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            "--api-key",
            "apikey",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["availableBalance"] == "250.00"
    assert data["currency"] == "EUR"


def test_cli_collection_request_to_pay(httpx_mock: HTTPXMock) -> None:
    """Test CLI collection request-to-pay command."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "token",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay",
        status_code=202,
    )

    with patch(
        "pymomo.products.collection.generate_reference_id",
        return_value="e4d6934c-6fa1-49b4-9c59-bf558661b17c",
    ):
        result = runner.invoke(
            app,
            [
                "collection",
                "request-to-pay",
                "256771234567",
                "50.00",
                "EUR",
                "ext-123",
                "--subscription-key",
                "key",
                "--api-user",
                "e4d6934c-6fa1-49b4-9c59-bf558661b17c",
                "--api-key",
                "apikey",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["reference_id"] == "e4d6934c-6fa1-49b4-9c59-bf558661b17c"


def test_cli_disbursement_balance(httpx_mock: HTTPXMock) -> None:
    """Test CLI disbursement balance command."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/token/",
        json={
            "access_token": "token",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/account/balance",
        json={"availableBalance": "350.00", "currency": "EUR"},
        status_code=200,
    )

    result = runner.invoke(
        app,
        [
            "disbursement",
            "balance",
            "--subscription-key",
            "key",
            "--api-user",
            "e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            "--api-key",
            "apikey",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["availableBalance"] == "350.00"
    assert data["currency"] == "EUR"


def test_cli_remittance_balance(httpx_mock: HTTPXMock) -> None:
    """Test CLI remittance balance command."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/remittance/token/",
        json={
            "access_token": "token",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/remittance/v1_0/account/balance",
        json={"availableBalance": "450.00", "currency": "EUR"},
        status_code=200,
    )

    result = runner.invoke(
        app,
        [
            "remittance",
            "balance",
            "--subscription-key",
            "key",
            "--api-user",
            "e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            "--api-key",
            "apikey",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["availableBalance"] == "450.00"
    assert data["currency"] == "EUR"


def test_cli_error_handling(httpx_mock: HTTPXMock) -> None:
    """Test that CLI errors print to stderr and exit with code 1."""
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        status_code=401,
    )

    err_runner = CliRunner()
    result = err_runner.invoke(
        app,
        [
            "collection",
            "balance",
            "--subscription-key",
            "key",
            "--api-user",
            "e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            "--api-key",
            "apikey",
        ],
    )
    assert result.exit_code == 1
    # Check either stderr (newer typer/click) or stdout (older typer/click which mixes them by default)
    try:
        error_msg = result.stderr
    except ValueError:
        error_msg = result.stdout
    assert "Error: " in error_msg
