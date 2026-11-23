from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import ValidationError

from py_momo_sdk.exceptions import WebhookVerificationError
from py_momo_sdk.models import TransactionResult

_SUPPORTED_HMAC_ALGORITHMS = {
    "sha256": hashlib.sha256,
    "sha512": hashlib.sha512,
}
_MAX_SIGNATURE_PARTS = 32
_MAX_V1_SIGNATURES = 16
_MAX_SIGNATURE_HEADER_LENGTH = 4096
_MAX_TIMESTAMP_DIGITS = 15
_IPV4_MAPPED_V6_NET = ipaddress.IPv6Network("::ffff:0:0/96")
DEFAULT_MAX_FUTURE_SKEW_SECONDS = 60.0


class WebhookHandler:
    """Utilities for verifying and processing MoMo webhook callbacks."""

    @staticmethod
    def verify_hmac_signature(
        payload: bytes,
        signature: str,
        secret: str,
        *,
        algorithm: str = "sha256",
    ) -> None:
        """Verify an HMAC signature over a raw webhook request body.

        Uses constant-time digest comparison to prevent timing side-channels.
        Supports either a raw hex digest or an ``"<algorithm>=<hex>"`` header
        value.

        Args:
            payload: Raw request body bytes.
            signature: Signature header value received with the webhook.
            secret: Shared secret key configured on the webhook gateway.
            algorithm: Hash algorithm name (``"sha256"`` or ``"sha512"``).

        Raises:
            WebhookVerificationError: If any input is missing, the algorithm is
                unsupported, or the signature does not match.
        """
        if not isinstance(algorithm, str):
            raise WebhookVerificationError(
                f"Unsupported webhook signature algorithm: {algorithm}"
            )
        algo = algorithm.lower()
        digest_fn = _SUPPORTED_HMAC_ALGORITHMS.get(algo)
        if digest_fn is None:
            raise WebhookVerificationError(
                f"Unsupported webhook signature algorithm: {algorithm}"
            )
        if not isinstance(payload, (bytes, bytearray)):
            raise WebhookVerificationError("Webhook payload must be bytes")
        if not isinstance(secret, str) or not secret:
            raise WebhookVerificationError(
                "Webhook verification secret must not be empty"
            )
        if not isinstance(signature, str) or not signature.strip():
            raise WebhookVerificationError("Webhook signature must not be empty")

        provided = signature.strip()
        prefix = f"{algo}="
        if provided.lower().startswith(prefix):
            provided = provided[len(prefix) :]

        expected_bytes = (
            hmac.new(
                secret.encode("utf-8"),
                bytes(payload),
                digest_fn,
            )
            .hexdigest()
            .encode("ascii")
        )

        if not hmac.compare_digest(expected_bytes, provided.lower().encode("utf-8")):
            raise WebhookVerificationError("Webhook signature verification failed")

    @staticmethod
    def verify_timestamped_hmac_signature(
        payload: bytes,
        signature_header: str,
        secret: str,
        *,
        tolerance_seconds: float = 300,
        max_future_skew_seconds: float = DEFAULT_MAX_FUTURE_SKEW_SECONDS,
        algorithm: str = "sha256",
        timestamp_separator: str = ".",
        replay_check: Callable[[str, bytes, int], bool] | None = None,
        now: float | None = None,
    ) -> None:
        """Verify a timestamped HMAC signature header (``t=<unix_ts>,v1=<hex>``).

        Signs ``f"{timestamp}{timestamp_separator}{payload}"``. Use
        ``timestamp_separator=""`` for gateways such as Wave (``Wave-Signature``)
        that concatenate the timestamp directly with the raw body, or ``"."``
        (default) for dot-delimited timestamped signatures.

        Args:
            replay_check: Optional callback ``(signature_header, payload, timestamp) -> bool``
                invoked after cryptographic signature verification. Returning
                ``False`` rejects the delivery as a replay.
        """
        import time

        if (
            not isinstance(timestamp_separator, str)
            or not timestamp_separator.isascii()
        ):
            raise WebhookVerificationError(
                "Webhook timestamp separator must be an ASCII string"
            )

        if not isinstance(algorithm, str):
            raise WebhookVerificationError(
                f"Unsupported webhook signature algorithm: {algorithm}"
            )
        algo = algorithm.lower()
        digest_fn = _SUPPORTED_HMAC_ALGORITHMS.get(algo)
        if digest_fn is None:
            raise WebhookVerificationError(
                f"Unsupported webhook signature algorithm: {algorithm}"
            )
        if not isinstance(payload, (bytes, bytearray)):
            raise WebhookVerificationError("Webhook payload must be bytes")
        if not isinstance(secret, str) or not secret:
            raise WebhookVerificationError(
                "Webhook verification secret must not be empty"
            )
        if not isinstance(signature_header, str) or not signature_header.strip():
            raise WebhookVerificationError("Webhook signature header must not be empty")
        if len(signature_header) > _MAX_SIGNATURE_HEADER_LENGTH:
            raise WebhookVerificationError(
                "Webhook signature header exceeds maximum allowed length"
            )
        if (
            type(tolerance_seconds) is bool
            or not isinstance(tolerance_seconds, (int, float))
            or not math.isfinite(float(tolerance_seconds))
            or tolerance_seconds <= 0
        ):
            raise WebhookVerificationError(
                "Webhook timestamp tolerance must be positive"
            )
        if (
            type(max_future_skew_seconds) is bool
            or not isinstance(max_future_skew_seconds, (int, float))
            or not math.isfinite(float(max_future_skew_seconds))
            or max_future_skew_seconds < 0
        ):
            raise WebhookVerificationError(
                "Webhook future skew tolerance must be non-negative"
            )
        if now is not None and (
            type(now) is bool
            or not isinstance(now, (int, float))
            or not math.isfinite(float(now))
        ):
            raise WebhookVerificationError("Invalid reference time for webhook check")

        parts = signature_header.split(",")
        if len(parts) > _MAX_SIGNATURE_PARTS:
            raise WebhookVerificationError("Malformed timestamped webhook signature")

        timestamp_str: str | None = None
        signatures: list[str] = []
        for part in parts:
            stripped_part = part.strip()
            if not stripped_part:
                raise WebhookVerificationError(
                    "Malformed timestamped webhook signature"
                )
            key, sep, val = stripped_part.partition("=")
            if not sep or not key.strip():
                raise WebhookVerificationError(
                    "Malformed timestamped webhook signature"
                )
            key = key.strip()
            if key == "t":
                if timestamp_str is not None:
                    raise WebhookVerificationError(
                        "Duplicate timestamp in webhook signature"
                    )
                timestamp_str = val.strip()
            elif key == "v1":
                if len(signatures) >= _MAX_V1_SIGNATURES:
                    raise WebhookVerificationError(
                        "Too many signature values in webhook header"
                    )
                sig_val = val.strip().lower()
                if not sig_val:
                    raise WebhookVerificationError(
                        "Malformed timestamped webhook signature"
                    )
                signatures.append(sig_val)

        if timestamp_str is None or not signatures:
            raise WebhookVerificationError("Malformed timestamped webhook signature")

        if (
            not timestamp_str
            or len(timestamp_str) > _MAX_TIMESTAMP_DIGITS
            or not timestamp_str.isascii()
            or not timestamp_str.isdigit()
            or (len(timestamp_str) > 1 and timestamp_str.startswith("0"))
        ):
            raise WebhookVerificationError("Invalid timestamp in webhook signature")

        ts = int(timestamp_str)
        current_time = time.time() if now is None else float(now)
        tolerance_f = float(tolerance_seconds)
        future_limit = min(tolerance_f, float(max_future_skew_seconds))
        if current_time - ts > tolerance_f:
            raise WebhookVerificationError("Webhook signature timestamp expired")
        if ts - current_time > future_limit:
            raise WebhookVerificationError(
                "Webhook signature timestamp is in the future"
            )

        raw_bytes = bytes(payload)
        signed_payload = (
            f"{timestamp_str}{timestamp_separator}".encode("ascii") + raw_bytes
        )
        expected_bytes = (
            hmac.new(
                secret.encode("utf-8"),
                signed_payload,
                digest_fn,
            )
            .hexdigest()
            .encode("ascii")
        )

        matched = False
        for sig in signatures:
            if hmac.compare_digest(expected_bytes, sig.encode("utf-8")):
                matched = True
        if not matched:
            raise WebhookVerificationError("Webhook signature verification failed")

        if replay_check is not None and not replay_check(
            signature_header, raw_bytes, ts
        ):
            raise WebhookVerificationError("Webhook signature replay detected")

    @staticmethod
    def verify_source_ip(
        remote_ip: str,
        allowed_networks: Sequence[str],
    ) -> None:
        """Verify that a webhook request originates from an allowed IP or CIDR range.

        Fails closed when ``allowed_networks`` is empty or any IP/CIDR entry is
        invalid. Rejects IPv6 zone identifiers (``%...``) and normalizes
        IPv4-mapped IPv6 addresses and CIDRs (``::ffff:0:0/96``) to IPv4.
        """
        if isinstance(allowed_networks, (str, bytes)) or not allowed_networks:
            raise WebhookVerificationError(
                "Allowed webhook IP networks list must not be empty"
            )
        if not isinstance(remote_ip, str) or "%" in remote_ip:
            raise WebhookVerificationError("Invalid webhook source IP address")
        try:
            addr: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(
                remote_ip.strip()
            )
        except ValueError as exc:
            raise WebhookVerificationError("Invalid webhook source IP address") from exc

        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped

        parsed_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for entry in allowed_networks:
            if not isinstance(entry, str) or not entry.strip() or "%" in entry:
                raise WebhookVerificationError(
                    "Invalid CIDR entry in allowed webhook networks"
                )
            try:
                net = ipaddress.ip_network(entry.strip(), strict=True)
            except ValueError as exc:
                raise WebhookVerificationError(
                    "Invalid CIDR entry in allowed webhook networks"
                ) from exc
            if isinstance(net, ipaddress.IPv6Network) and net.subnet_of(
                _IPV4_MAPPED_V6_NET
            ):
                v4_addr = net.network_address.ipv4_mapped
                if v4_addr is not None:
                    net = ipaddress.IPv4Network(
                        (v4_addr, net.prefixlen - 96), strict=True
                    )
            parsed_networks.append(net)

        for network in parsed_networks:
            if addr.version == network.version and addr in network:
                return

        raise WebhookVerificationError("Webhook source IP is not in allowed networks")

    @staticmethod
    def parse_transaction_notification(
        body: dict[str, Any], *, require_identifier: bool = False
    ) -> TransactionResult:
        """Parse and validate a webhook callback body into a TransactionResult model.

        Args:
            body: Decoded JSON dictionary from the webhook request body.
            require_identifier: When ``True``, require at least one transaction
                identifier (``financial_transaction_id`` or ``external_id``).

        Returns:
            A validated ``TransactionResult`` instance.

        Raises:
            WebhookVerificationError: If ``body`` is not a dictionary, fails
                model validation, or lacks a required transaction identifier.
        """
        if not isinstance(body, dict):
            raise WebhookVerificationError(
                "Webhook notification body must be a JSON object"
            )
        try:
            result = TransactionResult.model_validate(body)
        except ValidationError as exc:
            raise WebhookVerificationError(
                "Invalid webhook transaction notification payload"
            ) from exc
        if require_identifier and not (
            result.financial_transaction_id or result.external_id
        ):
            raise WebhookVerificationError(
                "Webhook transaction notification is missing a transaction identifier"
            )
        return result

    @staticmethod
    def is_successful(
        body: dict[str, Any], *, require_identifier: bool = False
    ) -> bool:
        """Check if a webhook callback body indicates a successful transaction."""
        result = WebhookHandler.parse_transaction_notification(
            body, require_identifier=require_identifier
        )
        return result.is_successful()
