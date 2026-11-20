from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class MockGatewayState:
    """In-memory transaction state for the local mobile money mock server."""

    default_status: str = "SUCCESSFUL"
    transactions: dict[str, dict[str, Any]] = field(default_factory=dict)
    wave_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)


def create_mock_server(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    default_status: str = "SUCCESSFUL",
) -> tuple[ThreadingHTTPServer, MockGatewayState]:
    """Create a local HTTP mock gateway server for MTN MoMo, Airtel, and Wave."""
    state = MockGatewayState(default_status=default_status)

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _send_json(self, code: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path.endswith("/token/") or path == "/auth/oauth2/token":
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
                ref = self.headers.get("X-Reference-Id", "mock-ref")
                body = self._read_json()
                state.transactions[ref] = {
                    "financialTransactionId": "mock-fin-001",
                    "externalId": body.get("externalId", "ext-mock"),
                    "amount": body.get("amount", "100"),
                    "currency": body.get("currency", "UGX"),
                    "status": state.default_status,
                }
                self._send_json(202, {"reference_id": ref})
                return

            if path == "/merchant/v1/payments/":
                body = self._read_json()
                ref = str(body.get("reference", "mock-airtel-ref"))
                tx = body.get("transaction", {})
                airtel_state = "TS" if state.default_status == "SUCCESSFUL" else "TIP"
                state.transactions[ref] = {
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
                sid = f"cos-{len(state.wave_sessions) + 1}"
                session = {
                    "id": sid,
                    "amount": str(body.get("amount", "100")),
                    "currency": str(body.get("currency", "XOF")),
                    "checkout_status": "open",
                    "payment_status": (
                        "succeeded"
                        if state.default_status == "SUCCESSFUL"
                        else "processing"
                    ),
                    "wave_launch_url": f"https://pay.wave.com/c/{sid}",
                    "client_reference": body.get("client_reference"),
                }
                state.wave_sessions[sid] = session
                self._send_json(200, session)
                return

            self._send_json(404, {"message": "Not found"})

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path.endswith("/account/balance"):
                self._send_json(
                    200, {"availableBalance": "10000.00", "currency": "EUR"}
                )
                return
            if path.startswith("/collection/v1_0/requesttopay/"):
                ref = path.rsplit("/", 1)[-1]
                tx = state.transactions.get(ref)
                if tx is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, tx)
                return
            if path.startswith("/standard/v1/payments/"):
                ref = path.rsplit("/", 1)[-1]
                tx = state.transactions.get(ref)
                if tx is None:
                    self._send_json(404, {"message": "Not found"})
                    return
                self._send_json(200, tx)
                return
            if path.startswith("/v1/checkout/sessions/"):
                sid = path.rsplit("/", 1)[-1]
                session = state.wave_sessions.get(sid)
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
) -> tuple[ThreadingHTTPServer, MockGatewayState, threading.Thread]:
    """Start a local mock gateway server in a daemon background thread."""
    server, state = create_mock_server(host, port, default_status=default_status)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, state, thread
