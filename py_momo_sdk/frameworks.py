from __future__ import annotations

import hmac
import importlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from py_momo_sdk.exceptions import WebhookVerificationError
from py_momo_sdk.telemetry import TelemetryHook, WebhookTelemetryEvent
from py_momo_sdk.webhooks import DEFAULT_MAX_FUTURE_SKEW_SECONDS, WebhookHandler

logger = logging.getLogger("py_momo_sdk.webhooks")
DEFAULT_MAX_WEBHOOK_BYTES = 1_048_576  # 1 MiB
_MAX_CONTENT_LENGTH_DIGITS = 20


def _emit_webhook_telemetry(
    telemetry: TelemetryHook | None,
    provider: str,
    verified: bool,
    reason: str | None = None,
) -> None:
    if telemetry is None:
        return
    try:
        telemetry.on_webhook(
            WebhookTelemetryEvent(provider=provider, verified=verified, reason=reason)
        )
    except Exception:
        logger.warning("Telemetry hook on_webhook raised an exception", exc_info=True)


def _validate_max_body_bytes(max_body_bytes: int) -> int:
    if (
        type(max_body_bytes) is bool
        or not isinstance(max_body_bytes, int)
        or max_body_bytes <= 0
    ):
        raise ValueError("max_body_bytes must be a positive integer")
    return max_body_bytes


def _validate_http_error_status(http_error_status: int | None) -> int | None:
    if http_error_status is None:
        return None
    if (
        type(http_error_status) is bool
        or not isinstance(http_error_status, int)
        or not (400 <= http_error_status <= 599)
    ):
        raise ValueError(
            "http_error_status must be an HTTP error status code between 400 and 599"
        )
    return http_error_status


def _extract_single_header(headers: Any, header_name: str) -> str | None:
    target = header_name.lower()

    raw_headers = getattr(headers, "raw", None)
    if isinstance(raw_headers, (list, tuple)):
        matched: str | None = None
        for entry in raw_headers:
            if (
                not isinstance(entry, (list, tuple))
                or len(entry) != 2
                or not isinstance(entry[0], (bytes, bytearray))
                or not isinstance(entry[1], (bytes, bytearray))
            ):
                raise WebhookVerificationError("Invalid webhook header entry")
            key_str = bytes(entry[0]).decode("latin-1")
            if key_str.lower() == target:
                if matched is not None:
                    raise WebhookVerificationError(
                        f"Duplicate {header_name} headers are not allowed"
                    )
                matched = bytes(entry[1]).decode("latin-1")
        return matched

    multi_items_fn = getattr(headers, "multi_items", None)
    if callable(multi_items_fn):
        matched = None
        for k, v in multi_items_fn():
            if not isinstance(k, str) or not isinstance(v, str):
                raise WebhookVerificationError("Invalid webhook header entry")
            if k.lower() == target:
                if matched is not None:
                    raise WebhookVerificationError(
                        f"Duplicate {header_name} headers are not allowed"
                    )
                matched = v
        return matched

    for list_method_name in ("getlist", "get_list", "getall"):
        list_fn = getattr(headers, list_method_name, None)
        if callable(list_fn):
            try:
                vals = list_fn(header_name)
            except KeyError:
                vals = []
            if len(vals) > 1:
                raise WebhookVerificationError(
                    f"Duplicate {header_name} headers are not allowed"
                )
            if len(vals) == 1:
                if not isinstance(vals[0], str):
                    raise WebhookVerificationError("Invalid webhook header value")
                return vals[0]
            return None

    items_fn = getattr(headers, "items", None)
    if not callable(items_fn):
        raise WebhookVerificationError("Invalid webhook headers mapping")

    matched = None
    for k, v in items_fn():
        if not isinstance(k, str) or not isinstance(v, str):
            raise WebhookVerificationError("Invalid webhook header entry")
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
    max_future_skew_seconds: float = DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    timestamp_separator: str = ".",
    replay_check: Callable[[str, bytes, int], bool] | None = None,
    algorithm: str = "sha256",
    remote_ip: str | None = None,
    allowed_networks: Sequence[str] | None = None,
    max_body_bytes: int = DEFAULT_MAX_WEBHOOK_BYTES,
    telemetry: TelemetryHook | None = None,
    provider: str = "unknown",
) -> None:
    """Verify an inbound webhook from any ASGI or WSGI framework using raw bytes.

    Args:
        raw_body: Exact unparsed request body bytes.
        headers: Case-insensitive or standard header mapping from the request.
        signature_header_name: Header name carrying the HMAC signature.
        secret: Shared webhook signing secret.
        timestamped: Set ``True`` for ``t=<ts>,v1=<hex>`` signatures (e.g. Wave).
        tolerance_seconds: Replay window in seconds when ``timestamped=True``.
        max_future_skew_seconds: Maximum allowed clock skew into the future.
        timestamp_separator: Separator between timestamp and body (``""`` for Wave,
            ``"."`` by default).
        replay_check: Optional replay-deduplication callback for timestamped hooks.
        algorithm: Hash algorithm (``"sha256"`` or ``"sha512"``).
        remote_ip: Optional peer IP address to enforce CIDR allowlisting.
        allowed_networks: Allowed IP/CIDR ranges when ``remote_ip`` is checked.
        max_body_bytes: Maximum accepted webhook payload size in bytes.
        telemetry: Optional ``TelemetryHook`` receiving ``WebhookTelemetryEvent``.
        provider: Provider identifier attached to emitted telemetry events.

    Raises:
        WebhookVerificationError: If IP allowlisting, size bounds, or HMAC
            verification fails.
    """
    limit = _validate_max_body_bytes(max_body_bytes)
    try:
        if allowed_networks is not None:
            if remote_ip is None:
                raise WebhookVerificationError("Webhook source IP address is required")
            WebhookHandler.verify_source_ip(remote_ip, allowed_networks)

        if not isinstance(raw_body, (bytes, bytearray)):
            raise WebhookVerificationError("Webhook payload must be bytes")
        if len(raw_body) > limit:
            raise WebhookVerificationError(
                "Webhook payload exceeds maximum allowed size"
            )

        sig_value = _extract_single_header(headers, signature_header_name) or ""
        if timestamped:
            WebhookHandler.verify_timestamped_hmac_signature(
                raw_body,
                sig_value,
                secret,
                tolerance_seconds=tolerance_seconds,
                max_future_skew_seconds=max_future_skew_seconds,
                algorithm=algorithm,
                timestamp_separator=timestamp_separator,
                replay_check=replay_check,
            )
        else:
            WebhookHandler.verify_hmac_signature(
                raw_body,
                sig_value,
                secret,
                algorithm=algorithm,
            )
    except WebhookVerificationError as exc:
        _emit_webhook_telemetry(telemetry, provider, verified=False, reason=str(exc))
        raise

    _emit_webhook_telemetry(telemetry, provider, verified=True)


def verify_constant_time_token(provided: str, expected: str) -> None:
    """Verify a static shared webhook token header (such as Flutterwave ``verif-hash``)."""
    if not isinstance(expected, str) or not expected:
        raise WebhookVerificationError("Expected webhook token must not be empty")
    if not isinstance(provided, str) or not provided:
        raise WebhookVerificationError("Provided webhook token must not be empty")
    if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise WebhookVerificationError("Webhook token verification failed")


def verify_static_token_webhook_request(
    *,
    headers: Mapping[str, str],
    token_header_name: str,
    expected_token: str,
    remote_ip: str | None = None,
    allowed_networks: Sequence[str] | None = None,
    telemetry: TelemetryHook | None = None,
    provider: str = "unknown",
) -> None:
    """Verify a static-token webhook (e.g. Flutterwave ``verif-hash``) with IP allowlisting and telemetry."""
    try:
        if allowed_networks is not None:
            if remote_ip is None:
                raise WebhookVerificationError("Webhook source IP address is required")
            WebhookHandler.verify_source_ip(remote_ip, allowed_networks)
        provided = _extract_single_header(headers, token_header_name) or ""
        verify_constant_time_token(provided, expected_token)
    except WebhookVerificationError as exc:
        _emit_webhook_telemetry(telemetry, provider, verified=False, reason=str(exc))
        raise

    _emit_webhook_telemetry(telemetry, provider, verified=True)


def _check_content_length_header(content_length_raw: Any, limit: int) -> None:
    if content_length_raw is None:
        return
    if (
        not isinstance(content_length_raw, (str, int))
        or type(content_length_raw) is bool
    ):
        raise WebhookVerificationError("Invalid Content-Length header on webhook")
    raw_str = str(content_length_raw).strip()
    if not raw_str:
        return
    if (
        len(raw_str) > _MAX_CONTENT_LENGTH_DIGITS
        or not raw_str.isascii()
        or not raw_str.isdigit()
    ):
        raise WebhookVerificationError("Invalid Content-Length header on webhook")
    if int(raw_str) > limit:
        raise WebhookVerificationError("Webhook payload exceeds maximum allowed size")


def create_asgi_webhook_verifier(
    *,
    secret: str,
    signature_header_name: str = "X-Signature",
    timestamped: bool = False,
    tolerance_seconds: float = 300,
    max_future_skew_seconds: float = DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    timestamp_separator: str = ".",
    replay_check: Callable[[str, bytes, int], bool] | None = None,
    algorithm: str = "sha256",
    allowed_networks: Sequence[str] | None = None,
    max_body_bytes: int = DEFAULT_MAX_WEBHOOK_BYTES,
    http_error_status: int | None = None,
    telemetry: TelemetryHook | None = None,
    provider: str = "unknown",
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
    validated_status = _validate_http_error_status(http_error_status)

    def _raise_error(exc: WebhookVerificationError) -> None:
        if validated_status is not None:
            try:
                starlette_exc = importlib.import_module("starlette.exceptions")
            except ImportError:
                raise exc from None
            http_exc_cls: Any = getattr(starlette_exc, "HTTPException", None)
            if http_exc_cls is not None:
                raise http_exc_cls(
                    status_code=validated_status, detail="Webhook verification failed"
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
                try:
                    async for chunk in stream_fn():
                        if len(buf) + len(chunk) > limit:
                            raise WebhookVerificationError(
                                "Webhook payload exceeds maximum allowed size"
                            )
                        buf.extend(chunk)
                except WebhookVerificationError:
                    raise
                except Exception as exc:
                    if exc.__class__.__name__ == "ClientDisconnect":
                        raise WebhookVerificationError(
                            "Client disconnected while reading webhook body"
                        ) from exc
                    raise
                raw_body = bytes(buf)
                # Cache verified body on Starlette/FastAPI Request so downstream
                # handlers can safely call await request.body() / request.json()
                try:
                    request._body = raw_body
                except (AttributeError, TypeError):
                    pass
            else:
                try:
                    raw_body = bytes(await request.body())
                except Exception as exc:
                    if exc.__class__.__name__ == "ClientDisconnect":
                        raise WebhookVerificationError(
                            "Client disconnected while reading webhook body"
                        ) from exc
                    raise
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
                max_future_skew_seconds=max_future_skew_seconds,
                timestamp_separator=timestamp_separator,
                replay_check=replay_check,
                algorithm=algorithm,
                remote_ip=None,
                allowed_networks=None,
                max_body_bytes=limit,
            )
            _emit_webhook_telemetry(telemetry, provider, verified=True)
            return raw_body
        except WebhookVerificationError as exc:
            _emit_webhook_telemetry(
                telemetry, provider, verified=False, reason=str(exc)
            )
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
    max_future_skew_seconds: float = DEFAULT_MAX_FUTURE_SKEW_SECONDS,
    timestamp_separator: str = ".",
    replay_check: Callable[[str, bytes, int], bool] | None = None,
    algorithm: str = "sha256",
    allowed_networks: Sequence[str] | None = None,
    max_body_bytes: int = DEFAULT_MAX_WEBHOOK_BYTES,
    telemetry: TelemetryHook | None = None,
    provider: str = "unknown",
) -> bytes:
    """Verify a Django ``HttpRequest`` using ``request.body`` and ``request.headers``."""
    limit = _validate_max_body_bytes(max_body_bytes)
    try:
        meta = getattr(request, "META", {})
        is_meta_mapping = isinstance(meta, Mapping)
        remote_ip = meta.get("REMOTE_ADDR") if is_meta_mapping else None
        if allowed_networks is not None:
            if remote_ip is None:
                raise WebhookVerificationError("Webhook source IP address is required")
            WebhookHandler.verify_source_ip(remote_ip, allowed_networks)

        cl_meta = meta.get("CONTENT_LENGTH") if is_meta_mapping else None
        cl_hdr = _extract_single_header(request.headers, "content-length")
        effective_cl = cl_hdr if (cl_hdr is not None and cl_hdr.strip()) else cl_meta
        _check_content_length_header(effective_cl, limit)

        try:
            raw_body = bytes(request.body)
        except Exception as exc:
            if exc.__class__.__name__ == "RequestDataTooBig":
                raise WebhookVerificationError(
                    "Webhook payload exceeds maximum allowed size"
                ) from exc
            raise
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
            max_future_skew_seconds=max_future_skew_seconds,
            timestamp_separator=timestamp_separator,
            replay_check=replay_check,
            algorithm=algorithm,
            remote_ip=None,
            allowed_networks=None,
            max_body_bytes=limit,
        )
    except WebhookVerificationError as exc:
        _emit_webhook_telemetry(telemetry, provider, verified=False, reason=str(exc))
        raise

    _emit_webhook_telemetry(telemetry, provider, verified=True)
    return raw_body
