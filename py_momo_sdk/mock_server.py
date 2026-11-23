from __future__ import annotations

import contextlib
import copy
import ipaddress
import json
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from py_momo_sdk.utils import validate_timeout

logger = logging.getLogger("py_momo_sdk.mock_server")

_VALID_MOCK_STATUSES = frozenset({"PENDING", "SUCCESSFUL", "FAILED"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_TOKEN_PATHS = frozenset(
    {
        "/collection/token/",
        "/disbursement/token/",
        "/remittance/token/",
        "/collection/v1_0/oauth2/token/",
        "/auth/oauth2/token",
        "/oauth/v3/token",
    }
)
_MTN_WRITE_PREFIXES: dict[str, str] = {
    "/collection/v1_0/requesttopay": "collection_rtp",
    "/collection/v2_0/requesttowithdraw": "collection_rtw",
    "/disbursement/v1_0/transfer": "disbursement_transfer",
    "/disbursement/v2_0/deposit": "disbursement_deposit",
    "/disbursement/v2_0/refund": "disbursement_refund",
    "/remittance/v1_0/transfer": "remittance_transfer",
}
_MTN_STATUS_PREFIXES: tuple[str, ...] = (
    "/collection/v1_0/requesttopay/",
    "/collection/v2_0/requesttowithdraw/",
    "/disbursement/v1_0/transfer/",
    "/disbursement/v2_0/deposit/",
    "/disbursement/v2_0/refund/",
    "/remittance/v1_0/transfer/",
)
_BALANCE_PATHS = frozenset(
    {
        "/collection/v1_0/account/balance",
        "/disbursement/v1_0/account/balance",
        "/remittance/v1_0/account/balance",
    }
)
_BALANCE_CURRENCY_PREFIXES: tuple[str, ...] = (
    "/collection/v1_0/account/balance/",
    "/disbursement/v1_0/account/balance/",
    "/remittance/v1_0/account/balance/",
)
DEFAULT_MAX_MOCK_BODY_BYTES = 1_048_576
DEFAULT_MAX_MOCK_ENTRIES = 10_000
DEFAULT_MAX_CONCURRENT_REQUESTS = 64
_MAX_CONTENT_LENGTH_DIGITS = 20


def _extract_single_suffix(path: str, prefix: str) -> str | None:
    if not path.startswith(prefix):
        return None
    suffix = path[len(prefix) :]
    if not suffix or "/" in suffix:
        return None
    return unquote(suffix)


def _is_ipv6_host(host: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(host), ipaddress.IPv6Address)
    except ValueError:
        return False


@dataclass
class MockGatewayState:
    """Thread-safe, bounded in-memory state for the local mobile money mock server."""

    default_status: str = "SUCCESSFUL"
    max_entries: int = DEFAULT_MAX_MOCK_ENTRIES
    transactions: dict[str, dict[str, Any]] = field(default_factory=dict)
    airtel_transactions: dict[str, dict[str, Any]] = field(default_factory=dict)
    wave_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    wave_payouts: dict[str, dict[str, Any]] = field(default_factory=dict)
    sandbox_users: dict[str, dict[str, Any]] = field(default_factory=dict)
    mpesa_transactions: dict[str, dict[str, Any]] = field(default_factory=dict)
    paystack_transactions: dict[str, dict[str, Any]] = field(default_factory=dict)
    flutterwave_transactions: dict[str, dict[str, Any]] = field(default_factory=dict)
    orange_transactions: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _session_counter: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        norm = (
            self.default_status.strip().upper()
            if isinstance(self.default_status, str)
            else ""
        )
        if norm not in _VALID_MOCK_STATUSES:
            raise ValueError(
                "default_status must be one of 'PENDING', 'SUCCESSFUL', or 'FAILED'"
            )
        self.default_status = norm
        if (
            type(self.max_entries) is bool
            or not isinstance(self.max_entries, int)
            or self.max_entries <= 0
        ):
            raise ValueError("max_entries must be a positive integer")

    def _put_bounded(
        self, store: dict[str, dict[str, Any]], key: str, value: dict[str, Any]
    ) -> None:
        if key not in store and len(store) >= self.max_entries:
            oldest = next(iter(store))
            del store[oldest]
        store[key] = value


def _make_server_class(
    *, use_ipv6: bool, max_concurrent_requests: int
) -> type[ThreadingHTTPServer]:
    semaphore = threading.BoundedSemaphore(max_concurrent_requests)

    class _BoundedThreadingHTTPServer(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if use_ipv6 else socket.AF_INET
        daemon_threads = True

        def process_request(self, request: Any, client_address: Any) -> None:
            if not semaphore.acquire(blocking=False):
                with contextlib.suppress(OSError):
                    request.sendall(
                        b"HTTP/1.1 503 Service Unavailable\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Content-Length: 31\r\n"
                        b"Connection: close\r\n\r\n"
                        b'{"message":"Server overloaded"}'
                    )
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except Exception:
                semaphore.release()
                raise

        def process_request_thread(self, request: Any, client_address: Any) -> None:
            try:
                super().process_request_thread(request, client_address)
            finally:
                semaphore.release()

    return _BoundedThreadingHTTPServer


def create_mock_server(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    default_status: str = "SUCCESSFUL",
    max_body_bytes: int = DEFAULT_MAX_MOCK_BODY_BYTES,
    max_entries: int = DEFAULT_MAX_MOCK_ENTRIES,
    request_timeout: float = 10.0,
    max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
    allow_non_loopback: bool = False,
) -> tuple[ThreadingHTTPServer, MockGatewayState]:
    """Create a local HTTP mock gateway server for MTN MoMo, Airtel, Wave, M-Pesa, Paystack, Flutterwave, and Orange Money."""
    if not isinstance(host, str) or not host.strip():
        raise ValueError("host must be a non-empty string")
    stripped_host = host.strip()
    if type(port) is bool or not isinstance(port, int) or not (0 <= port <= 65535):
        raise ValueError("port must be an integer between 0 and 65535")
    if (
        type(max_body_bytes) is bool
        or not isinstance(max_body_bytes, int)
        or max_body_bytes <= 0
    ):
        raise ValueError("max_body_bytes must be a positive integer")
    if (
        type(max_concurrent_requests) is bool
        or not isinstance(max_concurrent_requests, int)
        or max_concurrent_requests <= 0
    ):
        raise ValueError("max_concurrent_requests must be a positive integer")
    timeout_val = validate_timeout(request_timeout)
    if stripped_host.lower() not in _LOOPBACK_HOSTS:
        if not allow_non_loopback:
            raise ValueError(
                "Refusing to bind unauthenticated mock server to non-loopback host "
                "without allow_non_loopback=True"
            )
        logger.warning(
            "Binding unauthenticated mock gateway server to non-loopback host %s",
            stripped_host,
        )

    state = MockGatewayState(default_status=default_status, max_entries=max_entries)

    class _Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self._deadline = time.monotonic() + timeout_val
            self.connection.settimeout(timeout_val)

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _refresh_timeout(self) -> bool:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                self._send_json(408, {"message": "Request timeout"})
                return False
            self.connection.settimeout(remaining)
            return True

        def _send_json(self, code: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_chunked_body(self) -> bytes | None:
            buf = bytearray()
            while True:
                if not self._refresh_timeout():
                    return None
                size_line = self.rfile.readline(128)
                if not size_line or not size_line.endswith(b"\n"):
                    self._send_json(400, {"message": "Malformed chunked encoding"})
                    return None
                size_token = size_line.split(b";", 1)[0].strip()
                if not size_token or len(size_token) > 16:
                    self._send_json(400, {"message": "Invalid chunk size"})
                    return None
                try:
                    chunk_size = int(size_token, 16)
                except ValueError:
                    self._send_json(400, {"message": "Invalid chunk size"})
                    return None
                if chunk_size < 0:
                    self._send_json(400, {"message": "Invalid chunk size"})
                    return None
                if chunk_size == 0:
                    # Consume trailing headers / final CRLF
                    while True:
                        if not self._refresh_timeout():
                            return None
                        trailer = self.rfile.readline(1024)
                        if not trailer or trailer in (b"\r\n", b"\n"):
                            break
                    return bytes(buf)
                if len(buf) + chunk_size > max_body_bytes:
                    self._send_json(413, {"message": "Payload too large"})
                    return None
                if not self._refresh_timeout():
                    return None
                chunk_data = self.rfile.read(chunk_size)
                if len(chunk_data) < chunk_size:
                    self._send_json(400, {"message": "Truncated chunked request body"})
                    return None
                crlf = self.rfile.read(2)
                if crlf != b"\r\n":
                    self._send_json(400, {"message": "Malformed chunk terminator"})
                    return None
                buf.extend(chunk_data)

        def _read_raw_body(self) -> bytes | None:
            te_headers = self.headers.get_all("Transfer-Encoding") or []
            if te_headers:
                joined_te = ",".join(te_headers).strip().lower()
                if joined_te == "chunked":
                    return self._read_chunked_body()
                self._send_json(
                    501, {"message": "Unsupported Transfer-Encoding header"}
                )
                return None

            cl_headers = self.headers.get_all("Content-Length") or []
            if len(cl_headers) > 1:
                self._send_json(400, {"message": "Duplicate Content-Length header"})
                return None
            if not cl_headers:
                return b""
            stripped_cl = cl_headers[0].strip()
            if (
                not stripped_cl
                or len(stripped_cl) > _MAX_CONTENT_LENGTH_DIGITS
                or not stripped_cl.isascii()
                or not stripped_cl.isdigit()
            ):
                self._send_json(400, {"message": "Invalid Content-Length"})
                return None
            length = int(stripped_cl)
            if length > max_body_bytes:
                self._send_json(413, {"message": "Payload too large"})
                return None
            if length == 0:
                return b""
            if not self._refresh_timeout():
                return None
            raw = self.rfile.read(length)
            if len(raw) < length:
                self._send_json(400, {"message": "Truncated request body"})
                return None
            return raw

        def _read_json(self) -> dict[str, Any] | None:
            raw = self._read_raw_body()
            if raw is None:
                return None
            if not raw:
                return {}
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"message": "Invalid JSON payload"})
                return None
            if not isinstance(parsed, dict):
                self._send_json(400, {"message": "JSON payload must be an object"})
                return None
            return parsed

        def _airtel_status_code(self) -> str:
            if state.default_status == "SUCCESSFUL":
                return "TS"
            if state.default_status == "FAILED":
                return "TF"
            return "TIP"

        def _wave_status(self) -> str:
            if state.default_status == "SUCCESSFUL":
                return "succeeded"
            if state.default_status == "FAILED":
                return "failed"
            return "processing"

        def do_POST(self) -> None:
            self._deadline = time.monotonic() + timeout_val
            path = urlsplit(self.path).path

            if path in _TOKEN_PATHS:
                if self._read_raw_body() is None:
                    return
                self._send_json(
                    200,
                    {
                        "access_token": "mock-access-token",  # nosec B105
                        "token_type": "access_token",  # nosec B105
                        "expires_in": 3600,
                    },
                )
                return

            # MTN Sandbox Provisioning
            if path == "/v1_0/apiuser":
                body = self._read_json()
                if body is None:
                    return
                ref = self.headers.get("X-Reference-Id", "").strip() or "mock-user"
                with state.lock:
                    if ref in state.sandbox_users:
                        self._send_json(409, {"message": "Duplicate X-Reference-Id"})
                        return
                    state._put_bounded(
                        state.sandbox_users,
                        ref,
                        {
                            "providerCallbackHost": body.get(
                                "providerCallbackHost", "example.com"
                            ),
                            "targetEnvironment": "sandbox",
                        },
                    )
                self._send_json(201, {"reference_id": ref})
                return

            if path.startswith("/v1_0/apiuser/") and path.endswith("/apikey"):
                if self._read_raw_body() is None:
                    return
                uid = unquote(path[len("/v1_0/apiuser/") : -len("/apikey")])
                with state.lock:
                    exists = uid in state.sandbox_users
                if not exists:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(201, {"apiKey": f"mock-api-key-{uid}"})
                return

            # MTN Collection / Disbursement / Remittance writes with 409 Conflict check
            if path in _MTN_WRITE_PREFIXES:
                body = self._read_json()
                if body is None:
                    return
                ref = self.headers.get("X-Reference-Id", "").strip() or "mock-ref"
                entry = {
                    "financialTransactionId": "mock-fin-001",
                    "externalId": body.get("externalId", "ext-mock"),
                    "amount": body.get("amount", "100"),
                    "currency": body.get("currency", "UGX"),
                    "status": state.default_status,
                }
                with state.lock:
                    if ref in state.transactions:
                        self._send_json(409, {"message": "Duplicate X-Reference-Id"})
                        return
                    state._put_bounded(state.transactions, ref, entry)
                self._send_json(202, {"reference_id": ref})
                return

            if path == "/collection/v1_0/bc-authorize":
                if self._read_raw_body() is None:
                    return
                self._send_json(
                    200,
                    {
                        "auth_req_id": "mock-auth-req-id",
                        "interval": 5,
                        "expires_in": 300,
                    },
                )
                return

            # Airtel Money Collection & Disbursement
            if path in ("/merchant/v1/payments/", "/standard/v1/disbursements/"):
                body = self._read_json()
                if body is None:
                    return
                raw_tx = body.get("transaction")
                tx = raw_tx if isinstance(raw_tx, dict) else {}
                ref = str(tx.get("id") or body.get("reference") or "mock-airtel-ref")
                airtel_entry = {
                    "status": {
                        "code": "200",
                        "message": "Accepted",
                        "result_code": "DP008",
                    },
                    "data": {
                        "transaction": {
                            "id": ref,
                            "status": self._airtel_status_code(),
                            "amount": str(tx.get("amount", "100")),
                            "currency": str(tx.get("currency", "UGX")),
                        }
                    },
                }
                with state.lock:
                    state._put_bounded(state.airtel_transactions, ref, airtel_entry)
                self._send_json(
                    200,
                    {
                        "status": {
                            "code": "200",
                            "message": "Accepted",
                            "result_code": "DP008",
                        }
                    },
                )
                return

            # Wave Checkout Session & Payout
            if path == "/v1/checkout/sessions":
                body = self._read_json()
                if body is None:
                    return
                with state.lock:
                    state._session_counter += 1
                    sid = f"cos-{state._session_counter}"
                    session = {
                        "id": sid,
                        "amount": str(body.get("amount", "100")),
                        "currency": str(body.get("currency", "XOF")),
                        "checkout_status": "open",
                        "payment_status": self._wave_status(),
                        "wave_launch_url": f"https://pay.wave.com/c/{sid}",
                        "client_reference": body.get("client_reference"),
                    }
                    state._put_bounded(state.wave_sessions, sid, session)
                    response_copy = copy.deepcopy(session)
                self._send_json(200, response_copy)
                return

            if path == "/v1/payout":
                body = self._read_json()
                if body is None:
                    return
                with state.lock:
                    state._session_counter += 1
                    pid = f"pt-{state._session_counter}"
                    payout = {
                        "id": pid,
                        "receive_amount": str(
                            body.get("receive_amount", body.get("amount", "100"))
                        ),
                        "currency": str(body.get("currency", "XOF")),
                        "status": self._wave_status(),
                        "client_reference": body.get("client_reference"),
                    }
                    state._put_bounded(state.wave_payouts, pid, payout)
                    response_copy = copy.deepcopy(payout)
                self._send_json(200, response_copy)
                return

            # Safaricom M-Pesa Daraja
            if path == "/mpesa/stkpush/v1/processrequest":
                body = self._read_json()
                if body is None:
                    return
                with state.lock:
                    state._session_counter += 1
                    cid = f"ws_CO_mock_{state._session_counter}"
                    state._put_bounded(
                        state.mpesa_transactions,
                        cid,
                        {
                            "CheckoutRequestID": cid,
                            "ResultCode": (
                                "0"
                                if state.default_status == "SUCCESSFUL"
                                else (
                                    "1032" if state.default_status == "FAILED" else ""
                                )
                            ),
                            "ResultDesc": f"Mock status {state.default_status}",
                        },
                    )
                self._send_json(
                    200,
                    {
                        "MerchantRequestID": f"mr_{cid}",
                        "CheckoutRequestID": cid,
                        "ResponseCode": "0",
                        "ResponseDescription": "Success. Request accepted",
                    },
                )
                return

            if path == "/mpesa/stkpushquery/v1/query":
                body = self._read_json()
                if body is None:
                    return
                cid = str(body.get("CheckoutRequestID", ""))
                with state.lock:
                    raw_mpesa = state.mpesa_transactions.get(cid)
                    mpesa_tx = (
                        copy.deepcopy(raw_mpesa) if raw_mpesa is not None else None
                    )
                if mpesa_tx is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, mpesa_tx)
                return

            if path == "/mpesa/b2c/v3/paymentrequest":
                body = self._read_json()
                if body is None:
                    return
                ocid = str(body.get("OriginatorConversationID", "mock-oc-1"))
                self._send_json(
                    200,
                    {
                        "ConversationID": f"AG_mock_{ocid}",
                        "OriginatorConversationID": ocid,
                        "ResponseCode": "0",
                        "ResponseDescription": "Accept the service request successfully.",
                    },
                )
                return

            # Paystack
            if path in ("/transaction/initialize", "/transfer"):
                body = self._read_json()
                if body is None:
                    return
                ref = str(body.get("reference") or "ps-mock-ref")
                ps_status = (
                    "success"
                    if state.default_status == "SUCCESSFUL"
                    else ("failed" if state.default_status == "FAILED" else "pending")
                )
                with state.lock:
                    state._put_bounded(
                        state.paystack_transactions,
                        ref,
                        {
                            "status": True,
                            "data": {
                                "reference": ref,
                                "status": ps_status,
                                "amount": body.get("amount", 10000),
                                "currency": body.get("currency", "NGN"),
                                "authorization_url": f"https://checkout.paystack.com/{ref}",
                            },
                        },
                    )
                    resp = copy.deepcopy(state.paystack_transactions[ref])
                self._send_json(200, resp)
                return

            # Flutterwave
            if path in ("/v3/payments", "/v3/transfers"):
                body = self._read_json()
                if body is None:
                    return
                ref = str(body.get("tx_ref") or body.get("reference") or "flw-mock-ref")
                flw_status = (
                    "successful"
                    if state.default_status == "SUCCESSFUL"
                    else ("failed" if state.default_status == "FAILED" else "pending")
                )
                with state.lock:
                    state._put_bounded(
                        state.flutterwave_transactions,
                        ref,
                        {
                            "status": "success",
                            "data": {
                                "id": ref,
                                "reference": ref,
                                "status": flw_status,
                                "amount": body.get("amount", "100"),
                                "currency": body.get("currency", "NGN"),
                                "link": f"https://checkout.flutterwave.com/{ref}",
                            },
                        },
                    )
                    resp = copy.deepcopy(state.flutterwave_transactions[ref])
                self._send_json(200, resp)
                return

            # Orange Money
            if path.startswith("/orange-money-webpay/") and path.endswith(
                "/webpayment"
            ):
                body = self._read_json()
                if body is None:
                    return
                with state.lock:
                    state._session_counter += 1
                    pt = f"om-pay-{state._session_counter}"
                    om_status = (
                        "SUCCESS"
                        if state.default_status == "SUCCESSFUL"
                        else (
                            "FAILED" if state.default_status == "FAILED" else "PENDING"
                        )
                    )
                    state._put_bounded(
                        state.orange_transactions,
                        pt,
                        {"status": om_status, "order_id": body.get("order_id")},
                    )
                self._send_json(
                    201,
                    {
                        "pay_token": pt,
                        "payment_url": f"https://webpay.orange.com/{pt}",
                    },
                )
                return

            if path.startswith("/orange-money-webpay/") and path.endswith(
                "/transactionstatus"
            ):
                body = self._read_json()
                if body is None:
                    return
                pt = str(body.get("pay_token", ""))
                with state.lock:
                    raw_om = state.orange_transactions.get(pt)
                    om_tx = copy.deepcopy(raw_om) if raw_om is not None else None
                if om_tx is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, om_tx)
                return

            self._send_json(404, {"message": "Not found"})

        def do_GET(self) -> None:
            self._deadline = time.monotonic() + timeout_val
            split = urlsplit(self.path)
            path = split.path

            # M-Pesa OAuth token GET
            if path == "/oauth/v1/generate":
                self._send_json(
                    200,
                    {
                        "access_token": "mock-mpesa-token",
                        "expires_in": "3599",
                    },  # nosec B105
                )
                return

            # MTN Balances
            if path in _BALANCE_PATHS:
                self._send_json(
                    200, {"availableBalance": "10000.00", "currency": "EUR"}
                )
                return
            for bal_prefix in _BALANCE_CURRENCY_PREFIXES:
                bal_curr = _extract_single_suffix(path, bal_prefix)
                if bal_curr is not None:
                    self._send_json(
                        200,
                        {"availableBalance": "10000.00", "currency": bal_curr.upper()},
                    )
                    return

            # MTN Account Holder Active / BasicUserInfo
            if "/accountholder/" in path and path.endswith("/active"):
                self._send_json(200, {"result": True})
                return
            if "/accountholder/" in path and path.endswith("/basicuserinfo"):
                self._send_json(200, {"given_name": "Mock", "family_name": "User"})
                return

            # MTN Sandbox get user
            sandbox_uid = _extract_single_suffix(path, "/v1_0/apiuser/")
            if sandbox_uid is not None:
                with state.lock:
                    user = copy.deepcopy(state.sandbox_users.get(sandbox_uid))
                if user is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, user)
                return

            # MTN Transaction Statuses
            for status_prefix in _MTN_STATUS_PREFIXES:
                mtn_ref = _extract_single_suffix(path, status_prefix)
                if mtn_ref is not None:
                    with state.lock:
                        tx = copy.deepcopy(state.transactions.get(mtn_ref))
                    if tx is None:
                        self._send_json(404, {"message": "Not found"})
                        return
                    self._send_json(200, tx)
                    return

            # Airtel Status & Balance
            if path in ("/merchant/v2/wallets/balance/", "/standard/v1/users/balance"):
                self._send_json(
                    200,
                    {
                        "status": {"code": "200", "message": "OK", "result_code": "00"},
                        "data": {
                            "balance": "5000.00",
                            "currency": "UGX",
                            "wallet": {
                                "msisdn": "256750000000",
                                "balance": "5000.00",
                                "currency": "UGX",
                                "status": "ACTIVE",
                            },
                        },
                    },
                )
                return
            for airtel_prefix in (
                "/standard/v1/payments/",
                "/standard/v1/disbursements/",
            ):
                airtel_ref = _extract_single_suffix(path, airtel_prefix)
                if airtel_ref is not None:
                    with state.lock:
                        tx = copy.deepcopy(state.airtel_transactions.get(airtel_ref))
                    if tx is None:
                        self._send_json(404, {"message": "Not found"})
                        return
                    self._send_json(200, tx)
                    return

            # Wave Session, Payout, Balance
            if path == "/v1/balance":
                self._send_json(200, {"amount": "25000", "currency": "XOF"})
                return
            wave_sid = _extract_single_suffix(path, "/v1/checkout/sessions/")
            if wave_sid is not None:
                with state.lock:
                    session = copy.deepcopy(state.wave_sessions.get(wave_sid))
                if session is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, session)
                return
            wave_pid = _extract_single_suffix(path, "/v1/payout/")
            if wave_pid is not None:
                with state.lock:
                    payout = copy.deepcopy(state.wave_payouts.get(wave_pid))
                if payout is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, payout)
                return

            # Paystack Status & Balance
            if path == "/balance":
                self._send_json(
                    200,
                    {"status": True, "data": [{"balance": 100000, "currency": "NGN"}]},
                )
                return
            for ps_prefix in ("/transaction/verify/", "/transfer/verify/"):
                ps_ref = _extract_single_suffix(path, ps_prefix)
                if ps_ref is not None:
                    with state.lock:
                        ps_tx = copy.deepcopy(state.paystack_transactions.get(ps_ref))
                    if ps_tx is None:
                        self._send_json(404, {"message": "Not found"})
                        return
                    self._send_json(200, ps_tx)
                    return

            # Flutterwave Status & Balance
            if path == "/v3/transactions/verify_by_reference":
                qs = parse_qs(split.query)
                tx_ref = qs.get("tx_ref", [""])[0]
                with state.lock:
                    flw_tx = copy.deepcopy(state.flutterwave_transactions.get(tx_ref))
                if flw_tx is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, flw_tx)
                return
            flw_tr_id = _extract_single_suffix(path, "/v3/transfers/")
            if flw_tr_id is not None:
                with state.lock:
                    flw_tx = copy.deepcopy(
                        state.flutterwave_transactions.get(flw_tr_id)
                    )
                if flw_tx is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, flw_tx)
                return
            flw_curr = _extract_single_suffix(path, "/v3/balances/")
            if flw_curr is not None:
                self._send_json(
                    200,
                    {
                        "status": "success",
                        "data": {
                            "available_balance": 10000,
                            "currency": flw_curr.upper(),
                        },
                    },
                )
                return

            self._send_json(404, {"message": "Not found"})

    server_cls = _make_server_class(
        use_ipv6=_is_ipv6_host(stripped_host),
        max_concurrent_requests=max_concurrent_requests,
    )
    server = server_cls((stripped_host, port), _Handler)
    return server, state


def start_mock_server_thread(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    default_status: str = "SUCCESSFUL",
    max_body_bytes: int = DEFAULT_MAX_MOCK_BODY_BYTES,
    max_entries: int = DEFAULT_MAX_MOCK_ENTRIES,
    request_timeout: float = 10.0,
    max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
    allow_non_loopback: bool = False,
) -> tuple[ThreadingHTTPServer, MockGatewayState, threading.Thread]:
    """Start a local mock gateway server in a daemon background thread."""
    server, state = create_mock_server(
        host,
        port,
        default_status=default_status,
        max_body_bytes=max_body_bytes,
        max_entries=max_entries,
        request_timeout=request_timeout,
        max_concurrent_requests=max_concurrent_requests,
        allow_non_loopback=allow_non_loopback,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, state, thread
