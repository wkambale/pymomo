from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from py_momo_sdk.utils import validate_timeout

logger = logging.getLogger("py_momo_sdk.mock_server")

_VALID_MOCK_STATUSES = frozenset({"PENDING", "SUCCESSFUL", "FAILED"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_TOKEN_PATHS = frozenset(
    {
        "/collection/token/",
        "/disbursement/token/",
        "/remittance/token/",
        "/auth/oauth2/token",
    }
)
_BALANCE_PATHS = frozenset(
    {
        "/collection/v1_0/account/balance",
        "/disbursement/v1_0/account/balance",
        "/remittance/v1_0/account/balance",
    }
)
DEFAULT_MAX_MOCK_BODY_BYTES = 1_048_576
DEFAULT_MAX_MOCK_ENTRIES = 10_000


def _extract_single_suffix(path: str, prefix: str) -> str | None:
    if not path.startswith(prefix):
        return None
    suffix = path[len(prefix) :]
    if not suffix or "/" in suffix:
        return None
    return suffix


@dataclass
class MockGatewayState:
    """Thread-safe, bounded in-memory state for the local mobile money mock server."""

    default_status: str = "SUCCESSFUL"
    max_entries: int = DEFAULT_MAX_MOCK_ENTRIES
    transactions: dict[str, dict[str, Any]] = field(default_factory=dict)
    airtel_transactions: dict[str, dict[str, Any]] = field(default_factory=dict)
    wave_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
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


def create_mock_server(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    default_status: str = "SUCCESSFUL",
    max_body_bytes: int = DEFAULT_MAX_MOCK_BODY_BYTES,
    max_entries: int = DEFAULT_MAX_MOCK_ENTRIES,
    request_timeout: float = 10.0,
    allow_non_loopback: bool = False,
) -> tuple[ThreadingHTTPServer, MockGatewayState]:
    """Create a local HTTP mock gateway server for MTN MoMo, Airtel, and Wave."""
    if (
        type(max_body_bytes) is bool
        or not isinstance(max_body_bytes, int)
        or max_body_bytes <= 0
    ):
        raise ValueError("max_body_bytes must be a positive integer")
    timeout_val = validate_timeout(request_timeout)
    if host.strip().lower() not in _LOOPBACK_HOSTS:
        if not allow_non_loopback:
            raise ValueError(
                "Refusing to bind unauthenticated mock server to non-loopback host "
                "without allow_non_loopback=True"
            )
        logger.warning(
            "Binding unauthenticated mock gateway server to non-loopback host %s", host
        )

    state = MockGatewayState(default_status=default_status, max_entries=max_entries)

    class _Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(timeout_val)

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _send_json(self, code: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any] | None:
            raw_cl = self.headers.get("Content-Length")
            if raw_cl is None:
                length = 0
            else:
                stripped_cl = raw_cl.strip()
                if not stripped_cl.isascii() or not stripped_cl.isdigit():
                    self._send_json(400, {"message": "Invalid Content-Length"})
                    return None
                length = int(stripped_cl)
            if length > max_body_bytes:
                self._send_json(413, {"message": "Payload too large"})
                return None
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"message": "Invalid JSON payload"})
                return None
            if not isinstance(parsed, dict):
                self._send_json(400, {"message": "JSON payload must be an object"})
                return None
            return parsed

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in _TOKEN_PATHS:
                self._send_json(
                    200,
                    {
                        "access_token": "mock-access-token",  # nosec B105
                        "token_type": "access_token",  # nosec B105
                        "expires_in": 3600,
                    },
                )
                return

            if path == "/collection/v1_0/requesttopay":
                body = self._read_json()
                if body is None:
                    return
                ref = self.headers.get("X-Reference-Id", "mock-ref")
                entry = {
                    "financialTransactionId": "mock-fin-001",
                    "externalId": body.get("externalId", "ext-mock"),
                    "amount": body.get("amount", "100"),
                    "currency": body.get("currency", "UGX"),
                    "status": state.default_status,
                }
                with state.lock:
                    state._put_bounded(state.transactions, ref, entry)
                self._send_json(202, {"reference_id": ref})
                return

            if path == "/merchant/v1/payments/":
                body = self._read_json()
                if body is None:
                    return
                ref = str(body.get("reference", "mock-airtel-ref"))
                raw_tx = body.get("transaction")
                tx = raw_tx if isinstance(raw_tx, dict) else {}
                if state.default_status == "SUCCESSFUL":
                    airtel_state = "TS"
                elif state.default_status == "FAILED":
                    airtel_state = "TF"
                else:
                    airtel_state = "TIP"
                airtel_entry = {
                    "status": {
                        "code": "200",
                        "message": "Accepted",
                        "result_code": "DP008",
                    },
                    "data": {
                        "transaction": {
                            "id": ref,
                            "status": airtel_state,
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

            if path == "/v1/checkout/sessions":
                body = self._read_json()
                if body is None:
                    return
                if state.default_status == "SUCCESSFUL":
                    wave_pay_status = "succeeded"
                elif state.default_status == "FAILED":
                    wave_pay_status = "failed"
                else:
                    wave_pay_status = "processing"
                with state.lock:
                    state._session_counter += 1
                    sid = f"cos-{state._session_counter}"
                    session = {
                        "id": sid,
                        "amount": str(body.get("amount", "100")),
                        "currency": str(body.get("currency", "XOF")),
                        "checkout_status": "open",
                        "payment_status": wave_pay_status,
                        "wave_launch_url": f"https://pay.wave.com/c/{sid}",
                        "client_reference": body.get("client_reference"),
                    }
                    state._put_bounded(state.wave_sessions, sid, session)
                self._send_json(200, session)
                return

            self._send_json(404, {"message": "Not found"})

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in _BALANCE_PATHS:
                self._send_json(
                    200, {"availableBalance": "10000.00", "currency": "EUR"}
                )
                return
            mtn_ref = _extract_single_suffix(path, "/collection/v1_0/requesttopay/")
            if mtn_ref is not None:
                with state.lock:
                    tx = state.transactions.get(mtn_ref)
                if tx is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, tx)
                return
            airtel_ref = _extract_single_suffix(path, "/standard/v1/payments/")
            if airtel_ref is not None:
                with state.lock:
                    tx = state.airtel_transactions.get(airtel_ref)
                if tx is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, tx)
                return
            wave_sid = _extract_single_suffix(path, "/v1/checkout/sessions/")
            if wave_sid is not None:
                with state.lock:
                    session = state.wave_sessions.get(wave_sid)
                if session is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, session)
                return
            self._send_json(404, {"message": "Not found"})

    server = ThreadingHTTPServer((host, port), _Handler)
    return server, state


def start_mock_server_thread(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    default_status: str = "SUCCESSFUL",
    max_body_bytes: int = DEFAULT_MAX_MOCK_BODY_BYTES,
    max_entries: int = DEFAULT_MAX_MOCK_ENTRIES,
    request_timeout: float = 10.0,
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
        allow_non_loopback=allow_non_loopback,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, state, thread
