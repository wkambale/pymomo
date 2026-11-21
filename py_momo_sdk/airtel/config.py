from __future__ import annotations

import base64
import binascii
import importlib
from dataclasses import dataclass

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
            validate_base_url(self.base_url)

    def __repr__(self) -> str:
        return (
            f"AirtelConfig(client_id={self.client_id!r}, "
            f"client_secret=<redacted>, country={self.country!r}, "
            f"currency={self.currency!r}, pin=<redacted>, "
            f"environment={self.environment!r}, base_url={self.base_url!r}, "
            f"timeout={self.timeout!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()
