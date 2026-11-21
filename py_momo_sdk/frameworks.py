from __future__ import annotations

import hmac
import importlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from py_momo_sdk.exceptions import WebhookVerificationError
from py_momo_sdk.webhooks import WebhookHandler

DEFAULT_MAX_WEBHOOK_BYTES = 1_048_576  # 1 MiB


def _validate_max_body_bytes(max_body_bytes: int) -> int:
    if (
        type(max_body_bytes) is bool
        or not isinstance(max_body_bytes, int)
        or max_body_bytes <= 0
    ):
        raise ValueError("max_body_bytes must be a positive integer")
    return max_body_bytes


def _extract_single_header(headers: Mapping[str, str], header_name: str) -> str | None:
    target = header_name.lower()
    matched: str | None = None
    for k, v in headers.items():
        if k.lower() == target:
            if matched is not None:
                raise WebhookVerificationError(
                    f"Duplicate {header_name} headers are not allowed"
                )
            matched = v
    return matched


def verify_raw_webhook_request(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    signature_header_name: str,
    secret: str,
    timestamped: bool = False,
    tolerance_seconds: float = 300,
    algorithm: str = "sha256",
    remote_ip: str | None = None,
    allowed_networks: Sequence[str] | None = None,
    max_body_bytes: int = DEFAULT_MAX_WEBHOOK_BYTES,
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
        max_body_bytes: Maximum accepted webhook payload size in bytes.

    Raises:
        WebhookVerificationError: If IP allowlisting, size bounds, or HMAC
            verification fails.
    """
    limit = _validate_max_body_bytes(max_body_bytes)
    if allowed_networks is not None:
        if remote_ip is None:
            raise WebhookVerificationError("Webhook source IP address is required")
        WebhookHandler.verify_source_ip(remote_ip, allowed_networks)

    if not isinstance(raw_body, (bytes, bytearray)):
        raise WebhookVerificationError("Webhook payload must be bytes")
    if len(raw_body) > limit:
        raise WebhookVerificationError("Webhook payload exceeds maximum allowed size")

    sig_value = _extract_single_header(headers, signature_header_name) or ""
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
    if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise WebhookVerificationError("Webhook token verification failed")


def _check_content_length_header(content_length_raw: str | None, limit: int) -> None:
    if content_length_raw is None or not str(content_length_raw).strip():
        return
    raw_str = str(content_length_raw).strip()
    if not raw_str.isascii() or not raw_str.isdigit():
        raise WebhookVerificationError("Invalid Content-Length header on webhook")
    if int(raw_str) > limit:
        raise WebhookVerificationError("Webhook payload exceeds maximum allowed size")


def create_asgi_webhook_verifier(
    *,
    secret: str,
    signature_header_name: str = "X-Signature",
    timestamped: bool = False,
    tolerance_seconds: float = 300,
    algorithm: str = "sha256",
    allowed_networks: Sequence[str] | None = None,
    max_body_bytes: int = DEFAULT_MAX_WEBHOOK_BYTES,
    http_error_status: int | None = None,
) -> Callable[[Any], Awaitable[bytes]]:
    """Build an async FastAPI or Starlette dependency verifying raw webhook bodies.

    Example with FastAPI::

        verify_momo = create_asgi_webhook_verifier(
            secret=os.environ["WEBHOOK_SECRET"],
            http_error_status=401,
        )

        @app.post("/webhooks/momo")
        async def handle_webhook(raw_body: bytes = Depends(verify_momo)) -> dict[str, str]:
            return {"status": "accepted"}
    """
    limit = _validate_max_body_bytes(max_body_bytes)

    def _raise_error(exc: WebhookVerificationError) -> None:
        if http_error_status is not None:
            try:
                starlette_exc = importlib.import_module("starlette.exceptions")
            except ImportError:
                raise exc from None
            http_exc_cls: Any = getattr(starlette_exc, "HTTPException", None)
            if http_exc_cls is not None:
                raise http_exc_cls(
                    status_code=http_error_status, detail="Webhook verification failed"
                ) from exc
        raise exc

    async def _verify(request: Any) -> bytes:
        try:
            client_host = (
                request.client.host if getattr(request, "client", None) else None
            )
            if allowed_networks is not None:
                if client_host is None:
                    raise WebhookVerificationError(
                        "Webhook source IP address is required"
                    )
                WebhookHandler.verify_source_ip(client_host, allowed_networks)

            cl_val = _extract_single_header(request.headers, "content-length")
            _check_content_length_header(cl_val, limit)

            stream_fn = getattr(request, "stream", None)
            if callable(stream_fn):
                buf = bytearray()
                async for chunk in stream_fn():
                    buf.extend(chunk)
                    if len(buf) > limit:
                        raise WebhookVerificationError(
                            "Webhook payload exceeds maximum allowed size"
                        )
                raw_body = bytes(buf)
            else:
                raw_body = bytes(await request.body())
                if len(raw_body) > limit:
                    raise WebhookVerificationError(
                        "Webhook payload exceeds maximum allowed size"
                    )

            verify_raw_webhook_request(
                raw_body=raw_body,
                headers=request.headers,
                signature_header_name=signature_header_name,
                secret=secret,
                timestamped=timestamped,
                tolerance_seconds=tolerance_seconds,
                algorithm=algorithm,
                remote_ip=None,
                allowed_networks=None,
                max_body_bytes=limit,
            )
            return raw_body
        except WebhookVerificationError as exc:
            _raise_error(exc)
            raise  # unreachable; keeps mypy satisfied

    try:
        starlette_req = importlib.import_module("starlette.requests")
        req_cls: Any = getattr(starlette_req, "Request", None)
        if req_cls is not None:
            _verify.__annotations__["request"] = req_cls
    except ImportError:
        pass

    return _verify


def verify_django_webhook_request(
    request: Any,
    *,
    secret: str,
    signature_header_name: str = "X-Signature",
    timestamped: bool = False,
    tolerance_seconds: float = 300,
    algorithm: str = "sha256",
    allowed_networks: Sequence[str] | None = None,
    max_body_bytes: int = DEFAULT_MAX_WEBHOOK_BYTES,
) -> bytes:
    """Verify a Django ``HttpRequest`` using ``request.body`` and ``request.headers``."""
    limit = _validate_max_body_bytes(max_body_bytes)
    meta = getattr(request, "META", {})
    remote_ip = meta.get("REMOTE_ADDR") if isinstance(meta, dict) else None
    if allowed_networks is not None:
        if remote_ip is None:
            raise WebhookVerificationError("Webhook source IP address is required")
        WebhookHandler.verify_source_ip(remote_ip, allowed_networks)

    cl_meta = meta.get("CONTENT_LENGTH") if isinstance(meta, dict) else None
    cl_hdr = _extract_single_header(request.headers, "content-length")
    _check_content_length_header(cl_hdr if cl_hdr is not None else cl_meta, limit)

    raw_body = bytes(request.body)
    if len(raw_body) > limit:
        raise WebhookVerificationError("Webhook payload exceeds maximum allowed size")

    verify_raw_webhook_request(
        raw_body=raw_body,
        headers=request.headers,
        signature_header_name=signature_header_name,
        secret=secret,
        timestamped=timestamped,
        tolerance_seconds=tolerance_seconds,
        algorithm=algorithm,
        remote_ip=None,
        allowed_networks=None,
        max_body_bytes=limit,
    )
    return raw_body
