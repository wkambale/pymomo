from __future__ import annotations

import json
from unittest.mock import patch

from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from py_momo_sdk._cli import app

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
        "py_momo_sdk.sandbox.generate_reference_id",
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
                "https://example.com",
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
        "py_momo_sdk.products.collection.generate_reference_id",
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


def test_cli_sanitizes_unexpected_exceptions() -> None:
    """Verify unexpected internal exceptions do not dump raw exception text."""
    with patch(
        "py_momo_sdk._cli.PyMomoSDK",
        side_effect=RuntimeError("internal secret=super-secret-value"),
    ):
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
    assert result.exit_code == 1
    try:
        err_output = result.stderr
    except ValueError:
        err_output = result.stdout
    assert "RuntimeError" in err_output
    assert "super-secret-value" not in err_output


def test_cli_version() -> None:
    """Test --version and -V flags output the package version."""
    for flag in ("--version", "-V"):
        result = runner.invoke(app, [flag])
        assert result.exit_code == 0
        assert result.stdout.startswith("py-momo-sdk ")
        assert result.stdout.strip() != "py-momo-sdk 0.0.0"


def test_cli_collection_status(httpx_mock: HTTPXMock) -> None:
    """Test CLI collection status command."""
    reference_id = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
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
        url=f"https://sandbox.momodeveloper.mtn.com/collection/v1_0/requesttopay/{reference_id}",
        json={
            "financialTransactionId": "fin-tx-123",
            "externalId": "ext-123",
            "amount": "50.00",
            "currency": "EUR",
            "status": "SUCCESSFUL",
        },
        status_code=200,
    )

    result = runner.invoke(
        app,
        [
            "collection",
            "status",
            reference_id,
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
    assert data["status"] == "SUCCESSFUL"
    assert data["financialTransactionId"] == "fin-tx-123"


def test_cli_base_url_override(httpx_mock: HTTPXMock) -> None:
    """Test CLI --base-url option routes requests to the custom HTTPS endpoint."""
    httpx_mock.add_response(
        method="POST",
        url="https://mock.momo.example.com/collection/token/",
        json={
            "access_token": "token",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://mock.momo.example.com/collection/v1_0/account/balance",
        json={"availableBalance": "99.50", "currency": "UGX"},
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
            "--base-url",
            "https://mock.momo.example.com",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["availableBalance"] == "99.50"
    assert data["currency"] == "UGX"


def test_cli_env_vars_security_rejections_carrier_and_mock(
    httpx_mock: HTTPXMock,
) -> None:
    """Test CLI PY_MOMO_SDK_* env vars, non-HTTPS/UUID rejections, carrier, and mock (#65)."""
    from unittest.mock import MagicMock

    # 1. Load credentials strictly via PY_MOMO_SDK_* environment variables (zero secret flags)
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/collection/token/",
        json={
            "access_token": "env-tok",
            "token_type": "access_token",
            "expires_in": 3600,
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://sandbox.momodeveloper.mtn.com/collection/v1_0/account/balance",
        json={"availableBalance": "777.00", "currency": "EUR"},
        status_code=200,
    )
    env_res = runner.invoke(
        app,
        ["collection", "balance"],
        env={
            "PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY": "env-sub",
            "PY_MOMO_SDK_COLLECTION_API_USER": "e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            "PY_MOMO_SDK_COLLECTION_API_KEY": "env-key",
        },
    )
    assert env_res.exit_code == 0
    assert json.loads(env_res.stdout)["availableBalance"] == "777.00"

    # 2. Non-HTTPS --base-url and invalid UUID reference_id rejected cleanly with exit code 1
    bad_url_res = runner.invoke(
        app,
        [
            "collection",
            "balance",
            "--base-url",
            "http://insecure.example.com",
        ],
        env={
            "PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY": "env-sub",
            "PY_MOMO_SDK_COLLECTION_API_USER": "e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            "PY_MOMO_SDK_COLLECTION_API_KEY": "env-key",
        },
    )
    assert bad_url_res.exit_code == 1

    bad_uuid_res = runner.invoke(
        app,
        ["collection", "status", "not-a-valid-uuid"],
        env={
            "PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY": "env-sub",
            "PY_MOMO_SDK_COLLECTION_API_USER": "e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            "PY_MOMO_SDK_COLLECTION_API_KEY": "env-key",
        },
    )
    assert bad_uuid_res.exit_code == 1

    # 3. Carrier detection subcommand
    carrier_res = runner.invoke(app, ["carrier", "+256771234567"])
    assert carrier_res.exit_code == 0
    assert json.loads(carrier_res.stdout) == {
        "country": "UG",
        "provider": "mtn_momo",
    }
    unknown_res = runner.invoke(app, ["carrier", "12345"])
    assert unknown_res.exit_code == 0
    assert json.loads(unknown_res.stdout) == {"country": None, "provider": None}

    # 4. Mock gateway subcommand: clean KeyboardInterrupt shutdown & security rejections
    fake_server = MagicMock()
    fake_server.server_address = ("127.0.0.1", 18090)
    fake_server.serve_forever.side_effect = KeyboardInterrupt()
    with patch(
        "py_momo_sdk._cli.create_mock_server",
        return_value=(fake_server, object()),
    ):
        mock_ok = runner.invoke(app, ["mock", "--host", "127.0.0.1", "--port", "18090"])
    assert mock_ok.exit_code == 0
    assert "127.0.0.1:18090" in mock_ok.stdout
    fake_server.server_close.assert_called_once()

    bad_mock_host = runner.invoke(app, ["mock", "--host", "0.0.0.0"])
    assert bad_mock_host.exit_code == 1
    bad_mock_status = runner.invoke(app, ["mock", "--status", "INVALID"])
    assert bad_mock_status.exit_code == 1


def test_cli_issue_90_exits_validation_secret_files_and_commands(
    httpx_mock: HTTPXMock, tmp_path
) -> None:
    """Verify Issue #90: typer.Exit(0) preserved, ValidationError sanitized, blank env/opts, secret files, and expanded commands."""
    import hashlib
    import hmac
    import stat

    import pytest
    import typer
    from pydantic import BaseModel, Field

    from py_momo_sdk._cli import handle_cli_exceptions

    # 1. handle_cli_exceptions preserves typer.Exit(code=0) and typer.Abort
    @handle_cli_exceptions
    def _clean_exit() -> None:
        raise typer.Exit(code=0)

    with pytest.raises(typer.Exit) as exc_info:
        _clean_exit()
    assert exc_info.value.exit_code == 0

    @handle_cli_exceptions
    def _abort_cmd() -> None:
        raise typer.Abort()

    with pytest.raises(typer.Abort):
        _abort_cmd()

    # 2. Pydantic ValidationError sanitized (does not leak raw secret input_value)
    class _SecretModel(BaseModel):
        count: int = Field(gt=0)

    @handle_cli_exceptions
    def _bad_model() -> None:
        _SecretModel(count="SECRET_INPUT_DO_NOT_LEAK")  # type: ignore[arg-type]

    with pytest.raises(typer.Exit) as val_exc:
        _bad_model()
    assert val_exc.value.exit_code == 1

    # 3. Secret files (--subscription-key-file, --api-key-file) + blank --base-url "" / whitespace env var
    sub_file = tmp_path / "sub.key"
    api_file = tmp_path / "api.key"
    sub_file.write_text("file-sub-key\n", encoding="utf-8")
    api_file.write_text("file-api-key\n", encoding="utf-8")

    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/token/",
        json={"access_token": "tok", "token_type": "access_token", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/disbursement/v1_0/transfer",
        status_code=202,
    )
    res_tr = runner.invoke(
        app,
        [
            "disbursement",
            "transfer",
            "256771234567",
            "100",
            "EUR",
            "ext-d1",
            "--subscription-key-file",
            str(sub_file),
            "--api-user",
            "e4d6934c-6fa1-49b4-9c59-bf558661b17c",
            "--api-key-file",
            str(api_file),
            "--base-url",
            "",
        ],
        env={"PY_MOMO_SDK_BASE_URL": "   ", "PY_MOMO_SDK_ENVIRONMENT": "  "},
    )
    assert res_tr.exit_code == 0
    assert "reference_id" in json.loads(res_tr.stdout)

    # 4. sandbox provision --output-file writes mode-0600 file and redacts stdout
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/v1_0/apiuser",
        status_code=201,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/e4d6934c-6fa1-49b4-9c59-bf558661b17c/apikey",
        json={"apiKey": "secret-prov-key"},
        status_code=201,
    )
    out_file = tmp_path / "creds.json"
    with patch(
        "py_momo_sdk.sandbox.generate_reference_id",
        return_value="e4d6934c-6fa1-49b4-9c59-bf558661b17c",
    ):
        prov_res = runner.invoke(
            app,
            [
                "sandbox",
                "provision",
                "--subscription-key-file",
                str(sub_file),
                "--output-file",
                str(out_file),
            ],
        )
    assert prov_res.exit_code == 0
    assert "secret-prov-key" not in prov_res.stdout
    assert (
        json.loads(out_file.read_text(encoding="utf-8"))["api_key"] == "secret-prov-key"
    )
    assert stat.S_IMODE(out_file.stat().st_mode) == 0o600

    # 5. webhook verify CLI subcommand
    payload_file = tmp_path / "wh.json"
    sec_file = tmp_path / "wh.sec"
    raw_wh = b'{"status":"SUCCESSFUL"}'
    payload_file.write_bytes(raw_wh)
    sec_file.write_text("cli-wh-secret\n", encoding="utf-8")
    sig = hmac.new(b"cli-wh-secret", raw_wh, hashlib.sha256).hexdigest()

    wh_ok = runner.invoke(
        app,
        [
            "webhook",
            "verify",
            "--signature",
            sig,
            "--payload-file",
            str(payload_file),
            "--secret-file",
            str(sec_file),
        ],
    )
    assert wh_ok.exit_code == 0
    assert json.loads(wh_ok.stdout) == {"verified": True}

    # 6. airtel balance CLI subcommand
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "air-cli-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/merchant/v2/wallets/balance/",
        json={
            "status": {"code": "200", "message": "OK", "result_code": "00"},
            "data": {
                "wallet": {
                    "msisdn": "256750000000",
                    "balance": "9900",
                    "currency": "UGX",
                    "status": "ACTIVE",
                }
            },
        },
        status_code=200,
    )
    air_sec_file = tmp_path / "airtel.sec"
    air_sec_file.write_text("air-secret\n", encoding="utf-8")
    air_res = runner.invoke(
        app,
        [
            "airtel",
            "balance",
            "--client-id",
            "air-id",
            "--client-secret-file",
            str(air_sec_file),
        ],
    )
    assert air_res.exit_code == 0
    assert json.loads(air_res.stdout)["data"]["wallet"]["balance"] == "9900"
