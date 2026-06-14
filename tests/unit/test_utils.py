from __future__ import annotations

import uuid

import pytest

from pymomo.utils import (
    build_basic_auth_header,
    generate_reference_id,
    normalise_msisdn,
    validate_reference_id,
)


def test_generate_reference_id() -> None:
    """Verify that generate_reference_id returns a valid UUID v4 string."""
    ref_id = generate_reference_id()
    assert isinstance(ref_id, str)
    # Parse as UUID to confirm validity
    parsed = uuid.UUID(ref_id)
    assert parsed.version == 4


def test_normalise_msisdn() -> None:
    """Verify that normalise_msisdn strips non-digit characters."""
    assert normalise_msisdn("+256-771-234 567") == "256771234567"
    assert normalise_msisdn("  123a456  ") == "123456"


def test_build_basic_auth_header() -> None:
    """Verify basic authorization header is encoded in standard base64 format."""
    header = build_basic_auth_header("user", "key")
    # 'user:key' base64 encoded is 'dXNlcjJrZXk=' (wait, 'user:key' is dXNlcjprZXk=)
    # Let's verify format starts with Basic and has the token
    assert header.startswith("Basic ")
    import base64

    encoded_part = header.split(" ")[1]
    decoded = base64.b64decode(encoded_part.encode("ascii")).decode("utf-8")
    assert decoded == "user:key"


def test_validate_reference_id() -> None:
    """Verify validate_reference_id raises value error on invalid UUID v4."""
    # Valid UUID v4
    valid_uuid = str(uuid.uuid4())
    validate_reference_id(valid_uuid)  # Should not raise

    # Invalid UUID string
    with pytest.raises(ValueError) as excinfo:
        validate_reference_id("not-a-uuid")
    assert "must be a valid UUID v4" in str(excinfo.value)

    # UUID v1 (invalid version)
    v1_uuid = str(uuid.uuid1())
    with pytest.raises(ValueError) as excinfo:
        validate_reference_id(v1_uuid)
    assert "must be a version 4 UUID" in str(excinfo.value)
