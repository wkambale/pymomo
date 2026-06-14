from __future__ import annotations

import re
import uuid


def generate_reference_id() -> str:
    """Return a random UUID v4 string suitable for X-Reference-Id."""
    return str(uuid.uuid4())


def normalise_msisdn(msisdn: str) -> str:
    """Strip non-digit characters and return a clean MSISDN string.

    Does not validate the number against any country's numbering plan.
    Callers are responsible for providing a valid number.
    """
    digits = re.sub(r"\D", "", msisdn)
    return digits


def build_basic_auth_header(api_user: str, api_key: str) -> str:
    """Return a Base64-encoded Basic authorisation header value.

    The format is 'Basic base64(api_user:api_key)'.
    """
    import base64

    raw = f"{api_user}:{api_key}"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def validate_reference_id(reference_id: str) -> None:
    """Validate that the given string is a valid UUID v4.

    Raises:
        ValueError: If the string is not a valid UUID v4 or is not version 4.
    """
    try:
        val = uuid.UUID(reference_id)
    except ValueError as exc:
        raise ValueError(
            f"The reference ID must be a valid UUID v4: {reference_id}"
        ) from exc
    if val.version != 4:
        raise ValueError(f"The reference ID must be a version 4 UUID: {reference_id}")
