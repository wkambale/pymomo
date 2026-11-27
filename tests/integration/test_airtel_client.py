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
        assert sent_body["subscriber"]["msisdn"] == "771234567"
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
        assert sent_body["payee"]["msisdn"] == "701987654"
        assert sent_body["transaction"]["amount"] == "10000"
        assert sent_body["transaction"]["id"] == ref
        assert sent_body["reference"] == ref
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
            url="https://openapiuat.airtel.africa/standard/v1/users/balance",
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
            client._http, "send", side_effect=httpx.TimeoutException("timeout")
        ):
            with pytest.raises(PyMomoSDKError) as excinfo:
                client.request("GET", "/test")
            assert "Airtel request timed out" in str(excinfo.value)

        # Connection error on request
        with patch.object(
            client._http, "send", side_effect=httpx.RequestError("connect")
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
        "send",
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
        "send",
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
        with pytest.raises(PyMomoSDKError) as exc418:
            client.request("GET", "/teapot")
        assert "Unexpected Airtel HTTP status: 418" in str(exc418.value)


def test_airtel_transaction_response_status_states() -> None:
    """Verify transaction status takes precedence over API envelope result_code."""
    from py_momo_sdk.airtel.models import (
        AirtelDisbursementPayee,
        AirtelDisbursementRequest,
        AirtelDisbursementTransaction,
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

    # Missing transaction status with success envelope maps cleanly to pending (never all-False)
    missing = AirtelTransactionResponse.model_validate(
        {
            "status": {"code": "200", "message": "Success", "result_code": "00"},
            "data": {"transaction": {"id": "tx-4"}},
        }
    )
    assert missing.is_successful() is False
    assert missing.is_pending() is True
    assert missing.is_failed() is False

    # AirtelDisbursementRequest must redact PIN in repr and str
    req = AirtelDisbursementRequest(
        payee=AirtelDisbursementPayee(msisdn="256701987654"),
        reference="ref-1",
        pin="secret-pin-4321",
        transaction=AirtelDisbursementTransaction(amount="5000", id="ref-1"),
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


def test_airtel_client_parity_injected_client_telemetry_and_errors(
    httpx_mock: HTTPXMock,
) -> None:
    """Test AirtelClient HttpClient parity (#63): injected client, retries, telemetry, 400/409/302, ORD-123."""
    import httpx

    from py_momo_sdk import RequestTelemetryEvent, TelemetryHook
    from py_momo_sdk.exceptions import BadRequestError, ConflictError

    events: list[RequestTelemetryEvent] = []

    class _Recorder(TelemetryHook):
        def on_request(self, event: RequestTelemetryEvent) -> None:
            events.append(event)

        def on_webhook(self, event: object) -> None:
            return None

    mock_airtel_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/retry-me",
        status_code=503,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/retry-me",
        json={"ok": True},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/nested-400",
        json={"status": {"code": "400", "message": "Invalid MSISDN format"}},
        status_code=400,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/nonstr-400",
        json={"message": ["list-not-str"]},
        status_code=400,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/dup-409",
        status_code=409,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/redir-302",
        status_code=302,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/merchant/v1/payments/",
        json={"status": {"code": "200", "message": "Accepted", "result_code": "DP008"}},
        status_code=200,
    )

    injected = httpx.Client(
        base_url="https://openapiuat.airtel.africa", follow_redirects=False
    )
    cfg = AirtelConfig(
        client_id="id",
        client_secret="sec",
        country="UG",
        currency="UGX",
        max_retries=1,
        retry_backoff=0.01,
        telemetry=_Recorder(),
    )
    with AirtelClient(cfg, client=injected) as client:
        resp = client.request("GET", "/retry-me", headers={"x-country": "KE"})
        assert resp.status_code == 200
        sent = next(r for r in httpx_mock.get_requests() if r.url.path == "/retry-me")
        assert sent.headers["x-country"] == "KE"
        assert len([k for k in sent.headers if k.lower() == "x-country"]) == 1

        with pytest.raises(BadRequestError, match="Invalid MSISDN format"):
            client.request("GET", "/nested-400")
        with pytest.raises(BadRequestError, match="Bad request"):
            client.request("GET", "/nonstr-400")
        with pytest.raises(ConflictError, match="Duplicate transaction reference"):
            client.request("GET", "/dup-409")
        with pytest.raises(PyMomoSDKError, match="redirect"):
            client.request("GET", "/redir-302")

        # Non-UUID merchant order reference works on Airtel
        assert (
            client.collection.request_to_pay(
                amount="500", payer_msisdn="256751234567", reference_id="ORD-123"
            )
            == "ORD-123"
        )
        with pytest.raises(ValueError, match="Invalid Airtel reference ID"):
            client.collection.get_payment_status("../bad")

    # Injected client must NOT be closed by AirtelClient.close()
    assert injected.is_closed is False
    injected.close()
    assert len(events) >= 5


def test_airtel_protocol_auth_and_predicate_fixes_issue_84() -> None:
    """Verify local MSISDN, HTTP 200 error envelope handling, OAuth guards, predicates, and packaging (#84)."""
    import json

    import httpx

    from py_momo_sdk.airtel.models import (
        AirtelTransactionResponse,
        normalise_airtel_msisdn,
    )
    from py_momo_sdk.airtel.products import AirtelCollection, AirtelDisbursement
    from py_momo_sdk.exceptions import BadRequestError, TransactionFailedError
    from py_momo_sdk.providers import AirtelMoneyProvider, PaymentRequest

    assert AirtelCollection is not None and AirtelDisbursement is not None

    # 1. Local MSISDN normalization for Airtel countries
    assert normalise_airtel_msisdn("+256701234567", "UG") == "701234567"
    assert normalise_airtel_msisdn("0701234567", "UG") == "701234567"
    assert normalise_airtel_msisdn("254731234567", "KE") == "731234567"
    assert normalise_airtel_msisdn("701234567", "UG") == "701234567"

    # 2. HTTP 200 business error envelopes raise instead of silently succeeding
    captured_bodies: list[dict[str, object]] = []

    def biz_err_handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/auth/oauth2/token":
            return httpx.Response(
                200, json={"access_token": "valid-tok", "expires_in": 180}
            )
        if req.url.path == "/standard/v1/disbursements/":
            captured_bodies.append(json.loads(req.content))
            return httpx.Response(
                200,
                json={
                    "data": {"transaction": {"id": "ref-tf", "status": "TF"}},
                    "status": {
                        "code": "400",
                        "message": "Invalid PIN",
                        "result_code": "DP00900001005",
                        "success": False,
                    },
                },
            )
        if req.url.path == "/standard/v1/users/balance":
            return httpx.Response(
                200,
                json={
                    "status": {
                        "code": "400",
                        "message": "Forbidden",
                        "result_code": None,
                        "success": False,
                    },
                    "data": {
                        "wallet": {
                            "msisdn": "701234567",
                            "balance": "0",
                            "currency": "UGX",
                            "status": "INACTIVE",
                        }
                    },
                },
            )
        captured_bodies.append(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "data": {"transaction": {"id": "ref-ok", "status": "TIP"}},
                "status": {
                    "code": "200",
                    "message": "Success",
                    "result_code": "DP00800001006",
                    "success": True,
                },
            },
        )

    cfg = AirtelConfig(
        client_id="id", client_secret="sec", country="UG", currency="UGX", pin="1234"
    )
    # Also test injected httpx.Client() with NO base_url (resolves via config.base_url!)
    with (
        httpx.Client(transport=httpx.MockTransport(biz_err_handler)) as no_base_http,
        AirtelClient(cfg, client=no_base_http) as client,
    ):
        with pytest.raises(TransactionFailedError, match="Invalid PIN"):
            client.disbursement.transfer("1000", "+256701234567", reference_id="ref-tf")
        assert captured_bodies[-1]["payee"] == {"msisdn": "701234567"}

        with pytest.raises(BadRequestError, match="Forbidden"):
            client.disbursement.get_balance()

        # AirtelMoneyProvider preserves external_id in Airtel's reference field
        provider = AirtelMoneyProvider(client)
        result = provider.collect(
            PaymentRequest(
                amount="1000",
                currency="UGX",
                payer_msisdn="+256701234567",
                external_id="MERCH-ORD-42",
                reference_id="ref-ok",
            )
        )
        assert result.reference_id == "ref-ok"
        assert captured_bodies[-1]["reference"] == "MERCH-ORD-42"

    # 3. OAuth rejects CRLF tokens, float('inf') expires_in, and 3xx redirects
    for bad_oauth in (
        httpx.Response(302, headers={"Location": "https://evil.example.com"}),
        httpx.Response(
            200, json={"access_token": "tok\r\nX-Bad: 1", "expires_in": 3600}
        ),
        httpx.Response(200, json={"access_token": "tok", "expires_in": 1.5}),
    ):
        with (
            httpx.Client(
                base_url=cfg.base_url or "https://openapiuat.airtel.africa",
                transport=httpx.MockTransport(lambda _r, resp=bad_oauth: resp),
            ) as raw,
            AirtelClient(cfg, client=raw) as client,
            pytest.raises(AuthenticationError),
        ):
            client.collection.get_payment_status("ref-1")

    # 4. AirtelTransactionResponse clean predicate partition (including DP0000000000 and null result_code)
    resp = AirtelTransactionResponse.model_validate(
        {
            "status": {
                "code": "200",
                "message": "Success",
                "result_code": "DP0000000000",
            },
            "data": {"transaction": {"id": "ref-1", "status": None}},
        }
    )
    assert (resp.is_successful(), resp.is_pending(), resp.is_failed()) == (
        False,
        True,
        False,
    )
    resp_fail = AirtelTransactionResponse.model_validate(
        {
            "status": {
                "code": "400",
                "message": "Failed",
                "result_code": None,
                "success": False,
            },
            "data": {"transaction": {"id": "ref-2", "status": None}},
        }
    )
    assert (
        resp_fail.is_successful(),
        resp_fail.is_pending(),
        resp_fail.is_failed(),
    ) == (False, False, True)


@pytest.mark.asyncio
async def test_issue_131_airtel_flat_balance_refund_kyc_and_webhook_hmac(
    httpx_mock: HTTPXMock,
) -> None:
    """Verify Issue #131: flat /standard/v1/users/balance, disbursement fields, refund, KYC, and Base64 HMAC."""
    import base64
    import hashlib
    import hmac

    from py_momo_sdk import (
        AirtelClient,
        AirtelConfig,
        AirtelMoneyProvider,
        AsyncAirtelClient,
        WebhookVerificationError,
    )

    cfg = AirtelConfig(
        client_id="cid-131",
        client_secret="csec-131",
        country="UG",
        currency="UGX",
        pin="1234",
        webhook_secret="airtel-wh-secret",
    )

    # Sync: token + flat balance + disbursement + refund + KYC user enquiry
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "tok-131-sync", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/standard/v1/users/balance",
        json={
            "data": {
                "balance": "245000.00",
                "currency": "UGX",
                "account_status": "ACTIVE",
                "account_type": "MERCHANT",
            },
            "status": {"code": "200", "message": "Success", "success": True},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/standard/v1/disbursements/",
        json={
            "data": {"transaction": {"id": "air-disb-131", "status": "TS"}},
            "status": {"code": "200", "message": "Success", "success": True},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/standard/v1/payments/refund",
        json={
            "data": {
                "transaction": {
                    "airtel_money_id": "MP131001",
                    "status": "TS",
                }
            },
            "status": {"code": "200", "message": "SUCCESS", "success": True},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/standard/v1/users/701234567",
        json={
            "data": {
                "first_name": "Grace",
                "last_name": "Kato",
                "msisdn": "701234567",
                "grade": "SUBS",
                "is_barred": False,
                "is_pin_set": True,
            },
            "status": {"code": "200", "message": "Success", "success": True},
        },
        status_code=200,
    )

    with AirtelClient(cfg) as sync_client:
        bal = sync_client.disbursement.get_balance()
        assert bal.balance == "245000.00"
        assert bal.currency == "UGX"
        assert bal.account_status == "ACTIVE"
        assert bal.account_type == "MERCHANT"
        assert bal.data.wallet.balance == "245000.00"

        sync_client.disbursement.transfer(
            "5000", "+256701234567", reference_id="air-disb-131"
        )
        disb_req = next(
            r
            for r in httpx_mock.get_requests()
            if r.url.path == "/standard/v1/disbursements/"
        )
        disb_body = json.loads(disb_req.read().decode("utf-8"))
        assert disb_body["transaction"]["country"] == "UG"
        assert disb_body["transaction"]["currency"] == "UGX"

        refund_res = sync_client.collection.refund("MP131001")
        assert refund_res.is_successful() is True

        kyc = sync_client.get_user_info("+256701234567")
        assert kyc.data.first_name == "Grace"
        assert kyc.data.is_pin_set is True

        # Base64 HMAC-SHA256 webhook verification
        raw_body = b'{"transaction":{"id":"tx-131","status_code":"TS"}}'
        good_sig = base64.b64encode(
            hmac.new(b"airtel-wh-secret", raw_body, hashlib.sha256).digest()
        ).decode("ascii")
        sync_client.verify_webhook(raw_body, good_sig)
        with pytest.raises(WebhookVerificationError):
            sync_client.verify_webhook(raw_body, "invalid-b64-sig")

        prov = AirtelMoneyProvider(sync_client)
        assert prov.capabilities.supports_webhook_hmac is True

    # Async parity: token + refund + KYC + verify_webhook
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/auth/oauth2/token",
        json={"access_token": "tok-131-async", "expires_in": 3600},
        status_code=200,
    )
    httpx_mock.add_response(
        method="POST",
        url="https://openapiuat.airtel.africa/standard/v1/payments/refund",
        json={
            "data": {"transaction": {"airtel_money_id": "MP131002", "status": "TS"}},
            "status": {"code": "200", "message": "SUCCESS", "success": True},
        },
        status_code=200,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://openapiuat.airtel.africa/standard/v1/users/701234567",
        json={
            "data": {"first_name": "Async", "last_name": "User", "msisdn": "701234567"},
            "status": {"code": "200", "message": "Success", "success": True},
        },
        status_code=200,
    )
    async with AsyncAirtelClient(cfg) as async_client:
        aref = await async_client.collection.refund("MP131002")
        assert aref.is_successful() is True
        akyc = await async_client.get_user_info("0701234567")
        assert akyc.data.first_name == "Async"
        async_client.verify_webhook(raw_body, good_sig)
