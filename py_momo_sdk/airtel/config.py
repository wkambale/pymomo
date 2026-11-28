from __future__ import annotations

import base64
import binascii
import importlib
import json
import os
from dataclasses import dataclass
from typing import Any

from py_momo_sdk.telemetry import TelemetryHook
from py_momo_sdk.utils import (
    validate_base_url,
    validate_country_code,
    validate_currency,
    validate_environment_name,
    validate_header_value,
    validate_max_retries,
    validate_retry_backoff,
    validate_timeout,
)

AIRTEL_SANDBOX_BASE_URL = "https://openapiuat.airtel.africa"
AIRTEL_PRODUCTION_BASE_URL = "https://openapi.airtel.africa"
_VALID_AIRTEL_ENVIRONMENTS = frozenset({"sandbox", "production"})


def _validate_encrypted_pin(pin: str) -> None:
    """Verify that a production Airtel PIN is an RSA-encrypted Base64 ciphertext."""
    stripped = pin.strip()
    if stripped.isdigit():
        raise ValueError(
            "Airtel production disbursements require an RSA-encrypted Base64 PIN; "
            "use encrypt_airtel_pin() rather than a plaintext numeric PIN"
        )
    try:
        decoded = base64.b64decode(stripped, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            "Airtel production disbursements require a valid Base64-encoded RSA PIN"
        ) from exc
    if len(decoded) < 64:
        raise ValueError(
            "Airtel production PIN ciphertext is too short; expected RSA-encrypted Base64 PIN"
        )


def encrypt_airtel_pin(pin: str, public_key_pem: str) -> str:
    """Encrypt an Airtel disbursement PIN with Airtel's RSA public key (PKCS#1 v1.5).

    Requires the optional ``cryptography`` package at runtime.
    """
    if not isinstance(pin, str) or not pin.strip():
        raise ValueError("pin must be a non-empty string")
    validate_header_value(pin, field_name="pin")
    if not isinstance(public_key_pem, str) or not public_key_pem.strip():
        raise ValueError("public_key_pem must be a non-empty PEM string")

    try:
        serialization = importlib.import_module(
            "cryptography.hazmat.primitives.serialization"
        )
        padding_mod = importlib.import_module(
            "cryptography.hazmat.primitives.asymmetric.padding"
        )
        rsa_mod = importlib.import_module(
            "cryptography.hazmat.primitives.asymmetric.rsa"
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Install 'cryptography' to encrypt Airtel PINs locally, "
            "or provide a pre-encrypted Base64 PIN"
        ) from exc

    pub_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    if not isinstance(pub_key, rsa_mod.RSAPublicKey):
        raise TypeError("public_key_pem must contain an RSA public key")
    ciphertext: bytes = pub_key.encrypt(
        pin.encode("utf-8"),
        padding_mod.PKCS1v15(),
    )
    return base64.b64encode(ciphertext).decode("ascii")


def sign_airtel_payload(
    payload: dict[str, Any] | bytes | str, public_key_pem: str
) -> tuple[str, str]:
    """Encrypt and sign an Airtel Money v2/v3 request payload.

    Returns ``(x_signature, x_key)`` headers per Airtel Africa Open API
    message-signing specification (AES-256-CBC payload encryption + RSA
    PKCS#1 v1.5 encryption of ``"<b64_key>:<b64_iv>"``). Requires the optional
    ``cryptography`` package at runtime.
    """
    if isinstance(payload, dict):
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    else:
        raise TypeError("payload must be a dict, str, or bytes")
    if not isinstance(public_key_pem, str) or not public_key_pem.strip():
        raise ValueError("public_key_pem must be a non-empty PEM string")

    try:
        serialization = importlib.import_module(
            "cryptography.hazmat.primitives.serialization"
        )
        asym_padding = importlib.import_module(
            "cryptography.hazmat.primitives.asymmetric.padding"
        )
        rsa_mod = importlib.import_module(
            "cryptography.hazmat.primitives.asymmetric.rsa"
        )
        sym_padding = importlib.import_module("cryptography.hazmat.primitives.padding")
        ciphers_mod = importlib.import_module("cryptography.hazmat.primitives.ciphers")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Install 'cryptography' (pip install py-momo-sdk[airtel]) to sign Airtel payloads"
        ) from exc

    pub_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    if not isinstance(pub_key, rsa_mod.RSAPublicKey):
        raise TypeError("public_key_pem must contain an RSA public key")

    aes_key = os.urandom(32)
    iv = os.urandom(16)
    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(raw) + padder.finalize()
    cipher = ciphers_mod.Cipher(
        ciphers_mod.algorithms.AES(aes_key), ciphers_mod.modes.CBC(iv)
    )
    encryptor = cipher.encryptor()
    encrypted_payload: bytes = encryptor.update(padded) + encryptor.finalize()
    x_signature = base64.b64encode(encrypted_payload).decode("ascii")

    key_iv_combo = (
        f"{base64.b64encode(aes_key).decode('ascii')}:"
        f"{base64.b64encode(iv).decode('ascii')}"
    ).encode("ascii")
    encrypted_key: bytes = pub_key.encrypt(key_iv_combo, asym_padding.PKCS1v15())
    x_key = base64.b64encode(encrypted_key).decode("ascii")
    return x_signature, x_key


@dataclass
class AirtelConfig:
    """Credentials and configurations for Airtel Money."""

    client_id: str
    client_secret: str
    country: str  # ISO country code (e.g. "UG")
    currency: str  # ISO currency code (e.g. "UGX")
    pin: str | None = None  # Needed for disbursements
    environment: str = "sandbox"
    base_url: str | None = None
    timeout: float = 30.0
    max_retries: int = 0
    retry_backoff: float = 0.5
    telemetry: TelemetryHook | None = None
    webhook_secret: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.client_id, str) or not self.client_id.strip():
            raise ValueError("client_id must be a non-empty string")
        if not isinstance(self.client_secret, str) or not self.client_secret.strip():
            raise ValueError("client_secret must be a non-empty string")
        validate_header_value(self.client_id, field_name="client_id")
        validate_header_value(self.client_secret, field_name="client_secret")
        self.country = validate_country_code(self.country)
        self.currency = validate_currency(self.currency)
        validate_environment_name(self.environment)
        if self.environment not in _VALID_AIRTEL_ENVIRONMENTS:
            raise ValueError("environment must be 'sandbox' or 'production'")
        if self.pin is not None:
            if not isinstance(self.pin, str) or not self.pin.strip():
                raise ValueError("pin must be a non-empty string")
            validate_header_value(self.pin, field_name="pin")
            if self.environment == "production":
                _validate_encrypted_pin(self.pin)
        if self.webhook_secret is not None:
            if (
                not isinstance(self.webhook_secret, str)
                or not self.webhook_secret.strip()
            ):
                raise ValueError("webhook_secret must not be blank")
            validate_header_value(self.webhook_secret, field_name="webhook_secret")
        self.timeout = validate_timeout(self.timeout)
        self.max_retries = validate_max_retries(self.max_retries)
        self.retry_backoff = validate_retry_backoff(self.retry_backoff)
        if self.base_url is None:
            self.base_url = (
                AIRTEL_SANDBOX_BASE_URL
                if self.environment == "sandbox"
                else AIRTEL_PRODUCTION_BASE_URL
            )
        else:
            validate_base_url(
                self.base_url, allow_localhost=(self.environment == "sandbox")
            )

    def __repr__(self) -> str:
        return (
            f"AirtelConfig(client_id=<redacted>, "
            f"client_secret=<redacted>, country={self.country!r}, "
            f"currency={self.currency!r}, pin=<redacted>, "
            f"environment={self.environment!r}, base_url={self.base_url!r}, "
            f"timeout={self.timeout!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()
