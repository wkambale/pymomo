from __future__ import annotations

import hashlib
import hmac
import ipaddress
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from py_momo_sdk.exceptions import WebhookVerificationError
from py_momo_sdk.models import TransactionResult

_SUPPORTED_HMAC_ALGORITHMS = {
    "sha256": hashlib.sha256,
    "sha512": hashlib.sha512,
}


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

        expected = hmac.new(
            secret.encode("utf-8"),
            bytes(payload),
            digest_fn,
        ).hexdigest()

        if not hmac.compare_digest(expected, provided.lower()):
            raise WebhookVerificationError("Webhook signature verification failed")

    @staticmethod
    def verify_timestamped_hmac_signature(
        payload: bytes,
        signature_header: str,
        secret: str,
        *,
        tolerance_seconds: int = 300,
        algorithm: str = "sha256",
        now: float | None = None,
    ) -> None:
        """Verify a timestamped HMAC signature header (``t=<unix_ts>,v1=<hex>``).

        Used by gateways such as Wave (``Wave-Signature``) and Stripe to prevent
        replay attacks by signing ``f"{timestamp}.{payload}"``.
        """
        import time

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
        if tolerance_seconds <= 0:
            raise WebhookVerificationError(
                "Webhook timestamp tolerance must be positive"
            )

        timestamp_str: str | None = None
        signatures: list[str] = []
        for part in signature_header.split(","):
            key, sep, val = part.strip().partition("=")
            if not sep:
                continue
            if key == "t":
                timestamp_str = val.strip()
            elif key == "v1":
                signatures.append(val.strip().lower())

        if timestamp_str is None or not signatures:
            raise WebhookVerificationError("Malformed timestamped webhook signature")

        try:
            ts = int(timestamp_str)
        except ValueError as exc:
            raise WebhookVerificationError(
                "Invalid timestamp in webhook signature"
            ) from exc

        current_time = time.time() if now is None else now
        if abs(current_time - ts) > tolerance_seconds:
            raise WebhookVerificationError("Webhook signature timestamp expired")

        signed_payload = f"{ts}.".encode() + bytes(payload)
        expected = hmac.new(
            secret.encode("utf-8"),
            signed_payload,
            digest_fn,
        ).hexdigest()

        if not any(hmac.compare_digest(expected, sig) for sig in signatures):
            raise WebhookVerificationError("Webhook signature verification failed")

    @staticmethod
    def verify_source_ip(
        remote_ip: str,
        allowed_networks: Sequence[str],
    ) -> None:
        """Verify that a webhook request originates from an allowed IP or CIDR range.

        Fails closed when ``allowed_networks`` is empty or any IP/CIDR entry is
        invalid.

        Args:
            remote_ip: Source IPv4 or IPv6 address of the incoming request.
            allowed_networks: Sequence of allowed IP addresses or CIDR ranges.

        Raises:
            WebhookVerificationError: If the allowlist is empty, an IP/CIDR is
                malformed, or ``remote_ip`` is not contained in any allowed network.
        """
        if not allowed_networks:
            raise WebhookVerificationError(
                "Allowed webhook IP networks list must not be empty"
            )
        try:
            addr = ipaddress.ip_address(remote_ip.strip())
        except (AttributeError, ValueError) as exc:
            raise WebhookVerificationError("Invalid webhook source IP address") from exc

        for entry in allowed_networks:
            try:
                network = ipaddress.ip_network(entry.strip(), strict=False)
            except (AttributeError, ValueError) as exc:
                raise WebhookVerificationError(
                    "Invalid CIDR entry in allowed webhook networks"
                ) from exc
            if addr.version == network.version and addr in network:
                return

        raise WebhookVerificationError("Webhook source IP is not in allowed networks")

    @staticmethod
    def parse_transaction_notification(body: dict[str, Any]) -> TransactionResult:
        """Parse and validate a webhook callback body into a TransactionResult model.

        Args:
            body: Decoded JSON dictionary from the webhook request body.

        Returns:
            A validated ``TransactionResult`` instance.

        Raises:
            WebhookVerificationError: If ``body`` is not a dictionary or fails
                model validation.
        """
        if not isinstance(body, dict):
            raise WebhookVerificationError(
                "Webhook notification body must be a JSON object"
            )
        try:
            return TransactionResult.model_validate(body)
        except ValidationError as exc:
            raise WebhookVerificationError(
                "Invalid webhook transaction notification payload"
            ) from exc

    @staticmethod
    def is_successful(body: dict[str, Any]) -> bool:
        """Check if a webhook callback body indicates a successful transaction."""
        result = WebhookHandler.parse_transaction_notification(body)
        return result.is_successful()
