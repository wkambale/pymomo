from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from py_momo_sdk import AirtelConfig, AsyncAirtelClient
from py_momo_sdk.exceptions import AuthenticationError, PyMomoSDKError


def _airtel_config() -> AirtelConfig:
    return AirtelConfig(
        client_id="async-airtel-client",
        client_secret="async-airtel-secret",
        country="UG",
        currency="UGX",
        pin="1234",
        environment="sandbox",
    )


@pytest.mark.asyncio
async def test_async_airtel_collection_and_status(httpx_mock: HTTPXMock) -> None:
    """Test AsyncAirtelClient collection request_to_pay and get_payment_status."""
    ref = "e4d6934c-6fa1-49b4-9c59-bf558661b17c"
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "airtel-tok-1", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/merchant/v1/payments/",
        json={
            "status": {
                "code": "200",
                "message": "Accepted",
                "result_code": "DP00800001006",
            }
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://openapiuat.airtel.africa/standard/v1/payments/{ref}",
        json={
            "status": {
                "code": "200",
                "message": "Success",
                "result_code": "DP00800001001",
            },
            "data": {
                "transaction": {
                    "id": ref,
                    "airtel_money_id": "MP261120.001",
                    "status": "TS",
                    "message": "Success",
                    "amount": "1500",
                    "currency": "UGX",
                }
            },
        },
        status_code=200,
    )

    async with AsyncAirtelClient(_airtel_config()) as client:
        out_ref = await client.collection.request_to_pay(
            amount="1500",
            payer_msisdn="256751234567",
            reference_id=ref,
        )
        assert out_ref == ref
        status = await client.collection.get_payment_status(ref)
        assert status.is_successful()
        assert status.data.transaction.airtel_money_id == "MP261120.001"


@pytest.mark.asyncio
async def test_async_airtel_disbursement_and_balance(httpx_mock: HTTPXMock) -> None:
    """Test AsyncAirtelClient disbursement transfer, status, and balance."""
    ref = "c38b25e7-a9a3-4874-9cb3-671e6268f760"
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "airtel-tok-2", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/standard/v1/disbursements/",
        json={
            "status": {
                "code": "200",
                "message": "Accepted",
                "result_code": "DP00900001001",
            }
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url=f"https://openapiuat.airtel.africa/standard/v1/disbursements/{ref}",
        json={
            "status": {"code": "200", "message": "Pending", "result_code": "00"},
            "data": {"transaction": {"id": ref, "status": "TIP"}},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/standard/v1/users/balance",
        json={
            "data": {
                "wallet": {
                    "msisdn": "256751234567",
                    "balance": "85000.00",
                    "currency": "UGX",
                    "status": "ACTIVE",
                }
            }
        },
        status_code=200,
    )

    async with AsyncAirtelClient(_airtel_config()) as client:
        out_ref = await client.disbursement.transfer(
            amount="2000",
            payee_msisdn="256751234567",
            reference_id=ref,
        )
        assert out_ref == ref
        tx = await client.disbursement.get_transfer_status(ref)
        assert tx.is_pending()
        bal = await client.disbursement.get_balance()
        assert bal.data.wallet.balance == "85000.00"


@pytest.mark.asyncio
async def test_async_airtel_401_retry_and_guards(httpx_mock: HTTPXMock) -> None:
    """Test AsyncAirtelClient 401 token refresh, header guard, and missing PIN."""
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "expired-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/standard/v1/users/balance",
        status_code=401,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "fresh-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/standard/v1/users/balance",
        json={
            "data": {
                "wallet": {
                    "msisdn": "256751234567",
                    "balance": "100.00",
                    "currency": "UGX",
                    "status": "ACTIVE",
                }
            }
        },
        status_code=200,
    )

    async with AsyncAirtelClient(_airtel_config()) as client:
        bal = await client.disbursement.get_balance()
        assert bal.data.wallet.balance == "100.00"
        assert "async-airtel-secret" not in repr(client._auth)

        with pytest.raises(PyMomoSDKError, match="HTTP method"):
            await client.request("GET POST", "/merchant/v2/wallets/balance/")

    no_pin_cfg = AirtelConfig(
        client_id="id", client_secret="sec", country="UG", currency="UGX"
    )
    async with AsyncAirtelClient(no_pin_cfg) as client_no_pin:
        with pytest.raises(ValueError, match="pin is required"):
            await client_no_pin.disbursement.transfer("100", "256751234567")


@pytest.mark.asyncio
async def test_async_airtel_bad_auth_401(httpx_mock: HTTPXMock) -> None:
    """Test AsyncAirtelAuth raises AuthenticationError on HTTP 401."""
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        status_code=401,
    )
    async with AsyncAirtelClient(_airtel_config()) as client:
        with pytest.raises(AuthenticationError, match="Invalid or expired Airtel"):
            await client.disbursement.get_balance()


@pytest.mark.asyncio
async def test_async_airtel_http_error_mappings_and_header_guards(
    httpx_mock: HTTPXMock,
) -> None:
    """Test AsyncAirtelClient error status mappings (400/404/409/500) and header guards."""
    from py_momo_sdk.exceptions import (
        BadRequestError,
        ConflictError,
        PyMomoSDKServerError,
        ResourceNotFoundError,
    )

    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "tok", "expires_in": 3600},
        status_code=200,
    )
    for code in (400, 404, 409, 502):
        httpx_mock.add_response(
            method="GET",
            url="https://openapiuat.airtel.africa/standard/v1/users/balance",
            json={"message": f"err {code}"},
            status_code=code,
        )

    async with AsyncAirtelClient(_airtel_config()) as client:
        with pytest.raises(BadRequestError):
            await client.disbursement.get_balance()
        with pytest.raises(ResourceNotFoundError):
            await client.disbursement.get_balance()
        with pytest.raises(ConflictError):
            await client.disbursement.get_balance()
        with pytest.raises(PyMomoSDKServerError):
            await client.disbursement.get_balance()

        with pytest.raises(PyMomoSDKError, match="HTTP header name"):
            await client.request(
                "GET",
                "/merchant/v2/wallets/balance/",
                headers={"Bad Header": "val"},
            )


@pytest.mark.asyncio
async def test_async_airtel_https_path_auth_stripping_and_injected_client(
    httpx_mock: HTTPXMock,
) -> None:
    """Mirror sync Airtel security tests onto AsyncAirtelClient (#65)."""
    import httpx

    # HTTPS enforcement & parser-differential URL rejections
    for bad_url in (
        "http://example.com",
        "http://localhost:80@evil.example.com",
        "ftp://evil.example.com",
        "https://user:pass@example.com",
    ):
        with pytest.raises(PyMomoSDKError):
            AsyncAirtelClient(
                AirtelConfig(
                    client_id="id",
                    client_secret="sec",
                    country="UG",
                    currency="UGX",
                    base_url=bad_url,
                )
            )

    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "async-air-tok", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/safe",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/redir",
        status_code=302,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/oversized",
        content=b"z" * 256,
        status_code=200,
    )

    shared = httpx.AsyncClient(
        base_url="https://openapiuat.airtel.africa", follow_redirects=False
    )
    try:
        async with AsyncAirtelClient(
            _airtel_config(), client=shared, max_response_bytes=64
        ) as client:
            for bad_path in (
                "http://evil.example.com/steal",
                "//evil.example.com/steal",
                "no-leading-slash",
                "/standard/v1/../steal",
            ):
                with pytest.raises(PyMomoSDKError):
                    await client.request("GET", bad_path)

            await client.request(
                "get",
                "/safe",
                headers={"authorization": "Bearer spoofed", "x-country": "KE"},
            )
            sent = next(r for r in httpx_mock.get_requests() if r.url.path == "/safe")
            assert sent.headers["Authorization"] == "Bearer async-air-tok"
            assert sent.headers["x-country"] == "KE"

            with pytest.raises(PyMomoSDKError, match="redirect"):
                await client.request("GET", "/redir")
            with pytest.raises(PyMomoSDKError, match="maximum allowed size"):
                await client.request("GET", "/oversized")

        assert shared.is_closed is False
    finally:
        await shared.aclose()
