from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from py_momo_sdk.exceptions import WebhookVerificationError
from py_momo_sdk.webhooks import WebhookHandler


def verify_raw_webhook_request(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    signature_header_name: str,
    secret: str,
    timestamped: bool = False,
    tolerance_seconds: int = 300,
    algorithm: str = "sha256",
    remote_ip: str | None = None,
    allowed_networks: Sequence[str] | None = None,
) -> None:
    """Verify an inbound webhook from any ASGI or WSGI framework using raw bytes.

    Args:
        raw_body: Exact unparsed request body bytes.
        headers: Case-insensitive or standard header mapping from the request.
        signature_header_name: Header name carrying the HMAC signature.
        secret: Shared webhook signing secret.
        timestamped: Set ``True`` for ``t=<ts>,v1=<hex>`` signatures (Wave, Stripe).
        tolerance_seconds: Replay window in seconds when ``timestamped=True``.
        algorithm: Hash algorithm (``"sha256"`` or ``"sha512"``).
        remote_ip: Optional peer IP address to enforce CIDR allowlisting.
        allowed_networks: Allowed IP/CIDR ranges when ``remote_ip`` is checked.

    Raises:
        WebhookVerificationError: If IP allowlisting or HMAC verification fails.
    """
    if allowed_networks is not None:
        if remote_ip is None:
            raise WebhookVerificationError("Webhook source IP address is required")
        WebhookHandler.verify_source_ip(remote_ip, allowed_networks)

    lowered = {k.lower(): v for k, v in headers.items()}
    sig_value = lowered.get(signature_header_name.lower(), "")
    if timestamped:
        WebhookHandler.verify_timestamped_hmac_signature(
            raw_body,
            sig_value,
            secret,
            tolerance_seconds=tolerance_seconds,
            algorithm=algorithm,
        )
    else:
        WebhookHandler.verify_hmac_signature(
            raw_body,
            sig_value,
            secret,
            algorithm=algorithm,
        )


def verify_constant_time_token(provided: str, expected: str) -> None:
    """Verify a static shared webhook token header (such as Flutterwave ``verif-hash``)."""
    if not isinstance(expected, str) or not expected:
        raise WebhookVerificationError("Expected webhook token must not be empty")
    if not isinstance(provided, str) or not provided:
        raise WebhookVerificationError("Provided webhook token must not be empty")
    if not hmac.compare_digest(provided, expected):
        raise WebhookVerificationError("Webhook token verification failed")


def create_asgi_webhook_verifier(
    *,
    secret: str,
    signature_header_name: str = "X-Signature",
    timestamped: bool = False,
    tolerance_seconds: int = 300,
    algorithm: str = "sha256",
    allowed_networks: Sequence[str] | None = None,
) -> Callable[[Any], Awaitable[bytes]]:
    """Build an async FastAPI or Starlette dependency verifying raw webhook bodies.

    Example with FastAPI::

        verify_momo = create_asgi_webhook_verifier(secret=os.environ["WEBHOOK_SECRET"])

        @app.post("/webhooks/momo")
        async def handle_webhook(raw_body: bytes = Depends(verify_momo)) -> dict[str, str]:
            return {"status": "accepted"}
    """

    async def _verify(request: Any) -> bytes:
        raw_body = await request.body()
        client_host = request.client.host if getattr(request, "client", None) else None
        verify_raw_webhook_request(
            raw_body=raw_body,
            headers=request.headers,
            signature_header_name=signature_header_name,
            secret=secret,
            timestamped=timestamped,
            tolerance_seconds=tolerance_seconds,
            algorithm=algorithm,
            remote_ip=client_host if allowed_networks is not None else None,
            allowed_networks=allowed_networks,
        )
        return bytes(raw_body)

    return _verify


def verify_django_webhook_request(
    request: Any,
    *,
    secret: str,
    signature_header_name: str = "X-Signature",
    timestamped: bool = False,
    tolerance_seconds: int = 300,
    algorithm: str = "sha256",
    allowed_networks: Sequence[str] | None = None,
) -> bytes:
    """Verify a Django ``HttpRequest`` using ``request.body`` and ``request.headers``."""
    raw_body = bytes(request.body)
    meta = getattr(request, "META", {})
    remote_ip = meta.get("REMOTE_ADDR") if isinstance(meta, dict) else None
    verify_raw_webhook_request(
        raw_body=raw_body,
        headers=request.headers,
        signature_header_name=signature_header_name,
        secret=secret,
        timestamped=timestamped,
        tolerance_seconds=tolerance_seconds,
        algorithm=algorithm,
        remote_ip=remote_ip if allowed_networks is not None else None,
        allowed_networks=allowed_networks,
    )
    return raw_body
