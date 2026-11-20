from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock

from py_momo_sdk.airtel.client import AirtelClient
from py_momo_sdk.airtel.config import AirtelConfig
from py_momo_sdk.exceptions import AuthenticationError, PyMomoSDKError


def mock_airtel_token(
    httpx_mock: HTTPXMock, base_url: str = "https://openapiuat.airtel.africa"
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{base_url}/auth/oauth2/token",
        json={"access_token": "mock-airtel-access-token", "expires_in": 3600},
        status_code=200,
    )


def test_airtel_client_https_enforcement() -> None:
    """Verify that AirtelClient enforces HTTPS on base URL unless localhost/127.0.0.1 is used."""
    # Invalid HTTP
    with pytest.raises(PyMomoSDKError) as excinfo:
        AirtelClient(
            AirtelConfig(
                client_id="id",
                client_secret="secret",
                country="UG",
                currency="UGX",
                base_url="http://example.com",
            )
        )
    assert "Base URL must use HTTPS" in str(excinfo.value)

    # Valid local HTTP
    AirtelClient(
        AirtelConfig(
            client_id="id",
            client_secret="secret",
            country="UG",
            currency="UGX",
            base_url="http://localhost",
        )
    )

    AirtelClient(
        AirtelConfig(
            client_id="id",
            client_secret="secret",
            country="UG",
            currency="UGX",
            base_url="http://127.0.0.1:8080",
        )
    )

    # Valid HTTPS
    client = AirtelClient(
        AirtelConfig(
            client_id="id",
            client_secret="secret",
            country="UG",
            currency="UGX",
            base_url="https://example.com",
        )
    )
    assert client._http.follow_redirects is False

    # URL parser differential bypasses must be rejected
    for bad_url in (
        "http://localhost:80@evil.example.com",
        " http://evil.example.com",
        "ftp://evil.example.com",
        "https://user:pass@example.com",
    ):
        with pytest.raises(PyMomoSDKError):
            AirtelClient(
                AirtelConfig(
                    client_id="id",
                    client_secret="secret",
                    country="UG",
                    currency="UGX",
                    base_url=bad_url,
                )
            )

    # Absolute or protocol-relative request paths must be rejected before sending auth
    for bad_path in (
        "http://evil.example.com/steal",
        "https://evil.example.com/steal",
        "//evil.example.com/steal",
        "no-leading-slash",
    ):
        with pytest.raises(PyMomoSDKError):
            client.request("GET", bad_path)


def test_airtel_config_repr_redaction() -> None:
    """Verify that AirtelConfig representation redacts credentials."""
    config = AirtelConfig(
        client_id="visible-id",
        client_secret="super-secret-key",
        country="UG",
        currency="UGX",
        pin="1234",
    )
    repr_str = repr(config)
    assert "visible-id" in repr_str
    assert "super-secret-key" not in repr_str
    assert "1234" not in repr_str
    assert "<redacted>" in repr_str


def test_airtel_collection_flow(httpx_mock: HTTPXMock) -> None:
    """Verify standard collection initiation and status check."""
    mock_airtel_token(httpx_mock)

    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/merchant/v1/payments/",
        json={"status": {"code": "200", "message": "Success", "result_code": "00"}},
        status_code=200,
    )

    config = AirtelConfig(
        client_id="my-id",
        client_secret="my-secret",
        country="UG",
        currency="UGX",
    )

    with AirtelClient(config) as client:
        # Request collection
        ref = client.collection.request_to_pay(
            amount="5000",
            payer_msisdn="+256-771-234-567",
        )
        assert len(ref) == 36  # Valid UUID v4 string length

        # Verify normalisation of msisdn in the sent requests
        reqs = httpx_mock.get_requests()
        pay_req = next(r for r in reqs if r.url.path == "/merchant/v1/payments/")
        sent_body = json.loads(pay_req.read().decode("utf-8"))
        assert sent_body["subscriber"]["msisdn"] == "256771234567"
        assert pay_req.headers["X-Country"] == "UG"
        assert pay_req.headers["X-Currency"] == "UGX"

        # Mock status query response
        httpx_mock.add_response(
            method="GET",
            url=f"https://openapiuat.airtel.africa/standard/v1/payments/{ref}",
            json={
                "status": {"code": "200", "message": "Success", "result_code": "00"},
                "data": {
                    "transaction": {
                        "airtel_money_id": "AM-12345",
                        "id": ref,
                        "status": "SUCCESSFUL",
                        "amount": "5000",
                        "currency": "UGX",
                        "reference": "ref-pay",
                    }
                },
            },
            status_code=200,
        )

        status_resp = client.collection.get_payment_status(ref)
        assert status_resp.is_successful()
        assert not status_resp.is_pending()
        assert status_resp.data.transaction.airtel_money_id == "AM-12345"


def test_airtel_disbursement_flow(httpx_mock: HTTPXMock) -> None:
    """Verify standard disbursement (transfer) initiation, status check, and balance check."""
    mock_airtel_token(httpx_mock)

    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/standard/v1/disbursements/",
        json={"status": {"code": "200", "message": "Success", "result_code": "00"}},
        status_code=200,
    )

    config = AirtelConfig(
        client_id="my-id",
        client_secret="my-secret",
        country="UG",
        currency="UGX",
        pin="9999",
    )

    with AirtelClient(config) as client:
        # Request disbursement
        ref = client.disbursement.transfer(
            amount="10000",
            payee_msisdn="+256 701 987 654",
        )
        assert len(ref) == 36

        reqs = httpx_mock.get_requests()
        disb_req = next(r for r in reqs if r.url.path == "/standard/v1/disbursements/")
        sent_body = json.loads(disb_req.read().decode("utf-8"))
        assert sent_body["number"] == "256701987654"
        assert sent_body["pin"] == "9999"

        # Mock status query response
        httpx_mock.add_response(
            method="GET",
            url=f"https://openapiuat.airtel.africa/standard/v1/disbursements/{ref}",
            json={
                "status": {"code": "200", "message": "Success", "result_code": "00"},
                "data": {
                    "transaction": {
                        "airtel_money_id": "AM-98765",
                        "id": ref,
                        "status": "SUCCESS",
                        "amount": "10000",
                        "currency": "UGX",
                        "reference": "ref-disb",
                    }
                },
            },
            status_code=200,
        )

        status_resp = client.disbursement.get_transfer_status(ref)
        assert status_resp.is_successful()

        # Mock balance check
        httpx_mock.add_response(
            method="GET",
            url="https://openapiuat.airtel.africa/merchant/v2/wallets/balance/",
            json={
                "data": {
                    "wallet": {
                        "msisdn": "256701222222",
                        "balance": "1500000.00",
                        "currency": "UGX",
                        "status": "active",
                    }
                }
            },
            status_code=200,
        )

        balance_resp = client.disbursement.get_balance()
        assert balance_resp.data.wallet.balance == "1500000.00"
        assert balance_resp.data.wallet.currency == "UGX"


def test_airtel_disbursement_requires_pin() -> None:
    """Verify disbursement raises ValueError when PIN is not configured."""
    config = AirtelConfig(
        client_id="my-id",
        client_secret="my-secret",
        country="UG",
        currency="UGX",
        # pin is omitted
    )

    with AirtelClient(config) as client:
        with pytest.raises(ValueError) as excinfo:
            client.disbursement.transfer("5000", "256771000000")
        assert "pin is required for Airtel disbursements" in str(excinfo.value)


def test_airtel_client_401_retry_once(httpx_mock: HTTPXMock) -> None:
    """Verify that a 401 Unauthorized triggers cache invalidation, token refresh, and retry."""
    # First token fetch (called during client construction/first request)
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "expired-token", "expires_in": 3600},
        status_code=200,
    )

    config = AirtelConfig(
        client_id="my-id",
        client_secret="my-secret",
        country="UG",
        currency="UGX",
    )

    client = AirtelClient(config)

    # First request returns 401
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/merchant/v1/payments/",
        status_code=401,
    )

    # Second token fetch on 401 refresh retry
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "fresh-token", "expires_in": 3600},
        status_code=200,
    )

    # Retried request succeeds
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/merchant/v1/payments/",
        json={"status": {"code": "200", "message": "Success", "result_code": "00"}},
        status_code=200,
    )

    ref = client.collection.request_to_pay("1000", "256771000000")
    assert len(ref) == 36

    # Verify requests sent
    reqs = httpx_mock.get_requests()

    # Check that the retried request had Bearer fresh-token
    auth_headers = [
        r.headers.get("Authorization")
        for r in reqs
        if r.url.path == "/merchant/v1/payments/"
    ]
    assert "Bearer expired-token" in auth_headers
    assert "Bearer fresh-token" in auth_headers


def test_airtel_client_exceptions(httpx_mock: HTTPXMock) -> None:
    """Verify connection errors and timeouts raise PyMomoSDKError in AirtelClient."""
    from unittest.mock import patch

    import httpx

    mock_airtel_token(httpx_mock)
    config = AirtelConfig(
        client_id="my-id",
        client_secret="my-secret",
        country="UG",
        currency="UGX",
    )
    with AirtelClient(config) as client:
        # Pre-fetch token to cache it, avoiding patching request during auth
        client._auth.get_token(client._http)

        # Timeout on request
        with patch.object(
            client._http, "request", side_effect=httpx.TimeoutException("timeout")
        ):
            with pytest.raises(PyMomoSDKError) as excinfo:
                client.request("GET", "/test")
            assert "Airtel request timed out" in str(excinfo.value)

        # Connection error on request
        with patch.object(
            client._http, "request", side_effect=httpx.RequestError("connect")
        ):
            with pytest.raises(PyMomoSDKError) as excinfo:
                client.request("GET", "/test")
            assert "Airtel connection error" in str(excinfo.value)


def test_airtel_client_401_refresh_failure(httpx_mock: HTTPXMock) -> None:
    """Verify that a token refresh failure inside 401 handler raises AuthenticationError."""
    # First token fetch
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "expired-token", "expires_in": 3600},
        status_code=200,
    )

    config = AirtelConfig(
        client_id="my-id",
        client_secret="my-secret",
        country="UG",
        currency="UGX",
    )
    client = AirtelClient(config)

    # Request returns 401
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/test",
        status_code=401,
    )

    # Next token refresh returns 401 (fails)
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        status_code=401,
    )

    with pytest.raises(AuthenticationError) as excinfo:
        client.request("GET", "/test")
    assert "Airtel authentication failed during token refresh" in str(excinfo.value)


def test_airtel_client_retry_exceptions(httpx_mock: HTTPXMock) -> None:
    """Verify that request errors or timeouts during retried request raise PyMomoSDKError."""
    from unittest.mock import patch

    import httpx

    # First token fetch
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "expired-token", "expires_in": 3600},
        status_code=200,
    )

    config = AirtelConfig(
        client_id="my-id",
        client_secret="my-secret",
        country="UG",
        currency="UGX",
    )
    client = AirtelClient(config)

    # Pre-fetch token to cache it
    client._auth.get_token(client._http)

    # Timeout on retried request
    with patch.object(
        client._http,
        "request",
        side_effect=[
            httpx.Response(
                401,
                request=httpx.Request("GET", "https://openapiuat.airtel.africa/test"),
            ),
            httpx.Response(
                200,
                json={"access_token": "fresh-token", "expires_in": 3600},
                request=httpx.Request(
                    "POST", "https://openapiuat.airtel.africa/auth/oauth2/token"
                ),
            ),
            httpx.TimeoutException("timeout"),
        ],
    ):
        with pytest.raises(PyMomoSDKError) as excinfo:
            client.request("GET", "/test")
        assert "Airtel request timed out on retry" in str(excinfo.value)

    # Connection error on retried request
    with patch.object(
        client._http,
        "request",
        side_effect=[
            httpx.Response(
                401,
                request=httpx.Request("GET", "https://openapiuat.airtel.africa/test"),
            ),
            httpx.Response(
                200,
                json={"access_token": "fresh-token", "expires_in": 3600},
                request=httpx.Request(
                    "POST", "https://openapiuat.airtel.africa/auth/oauth2/token"
                ),
            ),
            httpx.RequestError("connect"),
        ],
    ):
        with pytest.raises(PyMomoSDKError) as excinfo:
            client.request("GET", "/test")
        assert "Airtel connection error on retry" in str(excinfo.value)


def test_airtel_client_status_code_mappings(httpx_mock: HTTPXMock) -> None:
    """Verify that different HTTP status codes map to correct custom exceptions."""
    mock_airtel_token(httpx_mock)
    config = AirtelConfig(
        client_id="my-id",
        client_secret="my-secret",
        country="UG",
        currency="UGX",
    )

    with AirtelClient(config) as client:
        # HTTP 400 Bad Request
        httpx_mock.add_response(
            method="GET",
            url="https://openapiuat.airtel.africa/bad-req",
            json={"message": "invalid parameters"},
            status_code=400,
        )
        from py_momo_sdk.exceptions import (
            BadRequestError,
            ConflictError,
            PyMomoSDKServerError,
            ResourceNotFoundError,
        )

        with pytest.raises(BadRequestError) as excinfo:
            client.request("GET", "/bad-req")
        assert "invalid parameters" in str(excinfo.value)

        # HTTP 404 Not Found
        httpx_mock.add_response(
            method="GET",
            url="https://openapiuat.airtel.africa/not-found",
            status_code=404,
        )
        with pytest.raises(ResourceNotFoundError):
            client.request("GET", "/not-found")

        # HTTP 409 Conflict
        httpx_mock.add_response(
            method="GET",
            url="https://openapiuat.airtel.africa/conflict",
            status_code=409,
        )
        with pytest.raises(ConflictError):
            client.request("GET", "/conflict")

        # HTTP 500 Server Error
        httpx_mock.add_response(
            method="GET",
            url="https://openapiuat.airtel.africa/server-err",
            status_code=500,
        )
        with pytest.raises(PyMomoSDKServerError):
            client.request("GET", "/server-err")

        # HTTP 418 Unexpected Error
        httpx_mock.add_response(
            method="GET",
            url="https://openapiuat.airtel.africa/teapot",
            status_code=418,
        )
        with pytest.raises(PyMomoSDKError) as excinfo:
            client.request("GET", "/teapot")
        assert "Unexpected Airtel HTTP status: 418" in str(excinfo.value)


def test_airtel_transaction_response_status_states() -> None:
    """Verify transaction status takes precedence over API envelope result_code."""
    from py_momo_sdk.airtel.models import (
        AirtelDisbursementRequest,
        AirtelTransactionResponse,
    )

    # Failed transaction with HTTP/API result_code="00" must NOT be successful
    failed = AirtelTransactionResponse.model_validate(
        {
            "status": {"code": "200", "message": "Success", "result_code": "00"},
            "data": {"transaction": {"id": "tx-1", "status": "TF"}},
        }
    )
    assert failed.is_successful() is False
    assert failed.is_pending() is False
    assert failed.is_failed() is True

    # Pending and Initiated transactions must NOT be successful
    for pending_status in ("PENDING", "TIP", "Initiated", "TA"):
        pending = AirtelTransactionResponse.model_validate(
            {
                "status": {"code": "200", "message": "Success", "result_code": "00"},
                "data": {"transaction": {"id": "tx-2", "status": pending_status}},
            }
        )
        assert pending.is_successful() is False
        assert pending.is_pending() is True
        assert pending.is_failed() is False

    # Settled success statuses
    for ok_status in ("TS", "SUCCESS", "SUCCESSFUL"):
        ok = AirtelTransactionResponse.model_validate(
            {
                "status": {
                    "code": "200",
                    "message": "Success",
                    "result_code": "DP00800001001",
                },
                "data": {"transaction": {"id": "tx-3", "status": ok_status}},
            }
        )
        assert ok.is_successful() is True
        assert ok.is_pending() is False
        assert ok.is_failed() is False

    # Missing transaction status fails closed on is_successful()
    missing = AirtelTransactionResponse.model_validate(
        {
            "status": {"code": "200", "message": "Success", "result_code": "00"},
            "data": {"transaction": {"id": "tx-4"}},
        }
    )
    assert missing.is_successful() is False
    assert missing.is_pending() is False
    assert missing.is_failed() is False

    # AirtelDisbursementRequest must redact PIN in repr and str
    req = AirtelDisbursementRequest(
        amount="5000",
        number="256701987654",
        reference="ref-1",
        pin="secret-pin-4321",
    )
    assert "secret-pin-4321" not in repr(req)
    assert "secret-pin-4321" not in str(req)
    assert "pin=<redacted>" in repr(req)


def test_airtel_client_header_method_and_config_guards(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify AirtelClient validates method/headers, strips auth overrides, and validates config."""
    with pytest.raises(ValueError, match="control characters"):
        AirtelConfig(
            client_id="id\r\n",
            client_secret="sec",
            country="UG",
            currency="UGX",
        )
    with pytest.raises(ValueError, match="control characters"):
        AirtelConfig(
            client_id="id",
            client_secret="sec",
            country="UG",
            currency="UGX",
            pin="1234\n",
        )

    config = AirtelConfig(
        client_id="my-id",
        client_secret="my-secret",
        country="UG",
        currency="UGX",
    )
    with AirtelClient(config) as client:
        with pytest.raises(PyMomoSDKError, match="HTTP method"):
            client.request("GET\r\nEvil", "/test")
        with pytest.raises(PyMomoSDKError, match="header name"):
            client.request("GET", "/test", headers={"Bad Header": "v"})
        with pytest.raises(PyMomoSDKError, match="control characters"):
            client.request("GET", "/test", headers={"X-Custom": "ok\r\nInjected: 1"})

        mock_airtel_token(httpx_mock)
        httpx_mock.add_response(
            method="GET",
            url="https://openapiuat.airtel.africa/test",
            json={"ok": True},
            status_code=200,
        )
        client.request(
            "get",
            "/test",
            headers={"authorization": "Bearer spoofed", "X-Custom": "safe"},
        )
        req = next(r for r in httpx_mock.get_requests() if r.url.path == "/test")
        assert req.headers["Authorization"] == "Bearer mock-airtel-access-token"
        assert req.headers["X-Custom"] == "safe"
