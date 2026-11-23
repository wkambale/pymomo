from __future__ import annotations

import uuid

import pytest

from py_momo_sdk.models import AccountHolderIdType
from py_momo_sdk.utils import (
    build_basic_auth_header,
    encode_path_segment,
    generate_reference_id,
    normalise_msisdn,
    validate_account_holder_id_type,
    validate_currency,
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
    """Verify normalise_msisdn validates characters, strips 00 prefix, and enforces E.164 length bounds."""
    assert normalise_msisdn("+256-771-234 567") == "256771234567"
    assert normalise_msisdn("00256 771 234 567") == "256771234567"
    assert normalise_msisdn("(256) 771.234.567") == "256771234567"
    for bad in ("+++abc", "Call +256771234567 ext 9", "123a456", "123456", "1" * 16):
        with pytest.raises(ValueError, match="MSISDN"):
            normalise_msisdn(bad)


def test_validate_currency() -> None:
    """Verify validate_currency enforces three-letter ISO 4217 codes."""
    assert validate_currency("ugx") == "UGX"
    assert validate_currency("EUR") == "EUR"
    for bad in ("", "US", "UGXX", "../balance", "UGX?foo=1", "123"):
        with pytest.raises(ValueError, match="ISO 4217"):
            validate_currency(bad)


def test_validate_account_holder_id_type() -> None:
    """Verify account holder ID types accept enums and strings and reject traversal."""
    assert validate_account_holder_id_type(AccountHolderIdType.msisdn) == "msisdn"
    assert validate_account_holder_id_type("MSISDN") == "msisdn"
    assert validate_account_holder_id_type("email") == "email"
    assert validate_account_holder_id_type("party_code") == "party_code"
    for bad in ("", "../balance", "unknown"):
        with pytest.raises(ValueError, match="Account holder ID type"):
            validate_account_holder_id_type(bad)


def test_encode_path_segment() -> None:
    """Verify path segments are percent-encoded and traversal characters rejected."""
    assert encode_path_segment("user@example.com") == "user%40example.com"
    for bad in ("", ".", "..", "../balance", "a/b", "a\\b", "a?b", "a#b", "a\nb"):
        with pytest.raises(ValueError, match="Invalid path segment"):
            encode_path_segment(bad)


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

    with pytest.raises(ValueError, match="must not contain ':'"):
        build_basic_auth_header("user:extra", "key")
    with pytest.raises(ValueError, match="control characters"):
        build_basic_auth_header("user\r\n", "key")
    with pytest.raises(ValueError, match="control characters"):
        build_basic_auth_header("user", "key\n")


def test_validate_callback_host() -> None:
    """Verify validate_callback_host accepts HTTPS URLs and bare hostnames and rejects unsafe values."""
    from py_momo_sdk.utils import validate_callback_host

    assert validate_callback_host("example.com") == "example.com"
    assert validate_callback_host("https://example.com") == "https://example.com"
    assert validate_callback_host("http://localhost:8000") == "http://localhost:8000"
    for bad in (
        "",
        "http://evil.example.com",
        "https://user:pass@example.com",
        "bad host with spaces",
        "example.com\r\nX-Injected: 1",
    ):
        with pytest.raises(ValueError):
            validate_callback_host(bad)


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

    # Non-canonical UUID representations must be rejected
    for non_canonical in (
        f"urn:uuid:{valid_uuid}",
        f"{{{valid_uuid}}}",
        valid_uuid.replace("-", ""),
        f" {valid_uuid}",
    ):
        with pytest.raises(ValueError, match="must be a valid UUID v4"):
            validate_reference_id(non_canonical)


def test_url_path_numeric_and_polling_validation() -> None:
    """Verify strict URL, path, ASCII-digit, header, and polling validators."""
    from py_momo_sdk.exceptions import PyMomoSDKError
    from py_momo_sdk.utils import (
        detect_carrier_from_msisdn,
        validate_amount,
        validate_base_url,
        validate_callback_url,
        validate_header_value,
        validate_max_retries,
        validate_request_path,
        validate_retry_backoff,
        wait_for_settlement,
    )

    # Trailing empty query/fragment and invalid ports rejected in validate_base_url
    for bad_base in (
        "https://example.com?",
        "https://example.com#",
        "https://example.com:99999",
        "https://example.com/a b",
    ):
        with pytest.raises(PyMomoSDKError):
            validate_base_url(bad_base)

    # Dot-segments, fragment, and whitespace rejected in validate_request_path; query allowed
    assert (
        validate_request_path("/oauth/v1/generate?grant_type=client_credentials")
        == "/oauth/v1/generate?grant_type=client_credentials"
    )
    for bad_path in (
        "/collection/../disbursement/v1_0/account/balance",
        "/collection/./token/",
        "/collection/../token/?foo=1",
        "/collection/token/#frag",
        "/collection/token/ ",
    ):
        with pytest.raises(PyMomoSDKError):
            validate_request_path(bad_path)

    # Fragments, whitespace, and invalid ports rejected in validate_callback_url
    for bad_cb in (
        "https://example.com/hook#frag",
        "https://example.com/a b",
        "https://example.com:99999/hook",
    ):
        with pytest.raises(ValueError):
            validate_callback_url(bad_cb)

    # Non-ASCII Unicode digits rejected in amount and MSISDN/carrier
    for bad_amount in ("\u0661\u0660\u0660", "\uff11\uff10.\uff15"):
        with pytest.raises(ValueError, match="Amount"):
            validate_amount(bad_amount)
    with pytest.raises(ValueError, match="MSISDN"):
        normalise_msisdn("\u0667\u0667\u0661")
    with pytest.raises(ValueError, match="MSISDN"):
        normalise_msisdn("+256 \u0667\u0667\u0661 771234567")
    assert detect_carrier_from_msisdn("\u0662\u0665\u0666\u0667\u0667") is None

    # C1 control characters rejected in header values
    with pytest.raises(ValueError, match="control characters"):
        validate_header_value("bad\x85val", field_name="test_hdr")

    # Retry & polling validators reject bool, float max_retries, NaN, and inf
    for bad_retries in (True, False, -1, 1.5):  # type: ignore[list-item]
        with pytest.raises((TypeError, ValueError), match="max_retries"):
            validate_max_retries(bad_retries)  # type: ignore[arg-type]
    for bad_backoff in (True, 0, -0.5, float("inf"), float("nan")):
        with pytest.raises((TypeError, ValueError), match="retry_backoff"):
            validate_retry_backoff(bad_backoff)
    for bad_interval in (True, 0.0, -1.0, float("inf"), float("nan")):
        with pytest.raises((TypeError, ValueError), match="Polling"):
            wait_for_settlement(lambda: None, interval=bad_interval)
        with pytest.raises((TypeError, ValueError), match="Polling"):
            wait_for_settlement(lambda: None, max_interval=bad_interval)
    for bad_mult in (True, 0.5, float("inf"), float("nan")):
        with pytest.raises((TypeError, ValueError), match="Polling"):
            wait_for_settlement(lambda: None, backoff=bad_mult)


def test_core_parity_cleanups_issue_63(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test __version__, whitespace segment guard, 00/length carrier detection, and empty from_env."""
    import py_momo_sdk
    from py_momo_sdk import PyMomoSDKConfig
    from py_momo_sdk.config import SANDBOX
    from py_momo_sdk.utils import detect_carrier_from_msisdn, encode_path_segment

    assert isinstance(py_momo_sdk.__version__, str) and py_momo_sdk.__version__

    with pytest.raises(ValueError, match="Invalid path segment"):
        encode_path_segment("   ", field_name="ref")

    # 00 international prefix stripped and short numbers rejected
    assert detect_carrier_from_msisdn("00256771234567") == ("UG", "mtn_momo")
    assert detect_carrier_from_msisdn("25677") is None
    assert detect_carrier_from_msisdn("256771234567890123") is None

    # Empty env vars treated as unset in from_env()
    monkeypatch.setenv("PY_MOMO_SDK_ENVIRONMENT", "")
    monkeypatch.setenv("PY_MOMO_SDK_BASE_URL", "")
    monkeypatch.setenv("PY_MOMO_SDK_COLLECTION_SUBSCRIPTION_KEY", "sub")
    monkeypatch.setenv("PY_MOMO_SDK_COLLECTION_API_USER", "usr")
    monkeypatch.setenv("PY_MOMO_SDK_COLLECTION_API_KEY", "key")
    monkeypatch.setenv("PY_MOMO_SDK_COLLECTION_CALLBACK_URL", "")
    cfg = PyMomoSDKConfig.from_env()
    assert cfg.environment == SANDBOX
    assert cfg.base_url == "https://sandbox.momodeveloper.mtn.com"
    assert cfg.collection is not None
    assert cfg.collection.callback_url is None


def test_issue_80_ssrf_traversal_ports_headers_and_immutability() -> None:
    """Verify SSRF blocking, standard ports, encoded traversal, ASCII headers, and frozen configs (#80)."""
    from dataclasses import FrozenInstanceError

    import httpx

    from py_momo_sdk.config import (
        MTN_GHANA,
        SANDBOX,
        ProductConfig,
        PyMomoSDKConfig,
    )
    from py_momo_sdk.exceptions import PyMomoSDKError
    from py_momo_sdk.http import HttpClient
    from py_momo_sdk.models import TokenResponse
    from py_momo_sdk.providers.mpesa import MpesaConfig
    from py_momo_sdk.providers.orange import OrangeMoneyConfig
    from py_momo_sdk.utils import (
        validate_base_url,
        validate_callback_host,
        validate_callback_url,
        validate_header_value,
        validate_request_path,
    )

    # Valid explicit default ports and IPv6 localhost accepted in sandbox/local mode
    assert (
        validate_base_url("https://sandbox.momodeveloper.mtn.com:443")
        == "https://sandbox.momodeveloper.mtn.com:443"
    )
    assert (
        validate_callback_url("https://merchant.example.com:443/cb")
        == "https://merchant.example.com:443/cb"
    )
    assert validate_base_url("http://localhost:80") == "http://localhost:80"
    assert validate_base_url("http://[::1]:8000") == "http://[::1]:8000"

    # SSRF private/metadata/obfuscated IPs & malformed authorities rejected
    for bad_url in (
        "https://169.254.169.254",
        "https://10.0.0.1",
        "https://192.168.1.10",
        "https://172.16.0.1",
        "https://100.64.0.1",
        "https://[fe80::1]",
        "https://0x7f000001",
        "https://2130706433",
        "https://127.1",
        "https://sandbox.momodeveloper.mtn.com:",
        "https://sandbox.momodeveloper.mtn.com;a=b",
    ):
        with pytest.raises(PyMomoSDKError):
            validate_base_url(bad_url)
        with pytest.raises(ValueError):
            validate_callback_url(f"{bad_url}/cb")

    # Bare metadata/private IPs and >253-char hostnames rejected in validate_callback_host
    for bad_host in ("169.254.169.254", "10.0.0.1", "0x7f000001", "a." * 130 + "com"):
        with pytest.raises(ValueError):
            validate_callback_host(bad_host)

    # Production environments reject localhost / plaintext loopback
    with pytest.raises(PyMomoSDKError):
        PyMomoSDKConfig(
            environment=MTN_GHANA,
            base_url="http://127.0.0.1:8000",
        )
    with pytest.raises(ValueError):
        PyMomoSDKConfig(
            environment=MTN_GHANA,
            collection=ProductConfig(
                "sub", "user", "key", callback_url="http://127.0.0.1/cb"
            ),
        )

    # Encoded path traversal & disallowed query strings rejected
    for bad_path in (
        "/collection/%2e%2e/disbursement/v1_0/transfer",
        "/collection/%2E%2E/disbursement/v1_0/transfer",
        "/collection/%2f../token/",
        "/collection/%5c/token/",
        "/collection/%252e%252e/token/",
    ):
        with pytest.raises(PyMomoSDKError):
            validate_request_path(bad_path)
    with pytest.raises(PyMomoSDKError):
        validate_request_path(
            "/collection/v1_0/account/balance?admin=true", allow_query=False
        )

    # Non-ASCII headers, token whitespace, and ':' in Basic-auth usernames rejected
    with pytest.raises(ValueError, match="printable ASCII"):
        validate_header_value("sub\u0100key", field_name="subscription_key")
    with pytest.raises(ValueError, match="whitespace"):
        TokenResponse(access_token="tok1 tok2", token_type="Bearer", expires_in=60)
    with pytest.raises(ValueError, match="':'"):
        ProductConfig("sub", "user:colon", "key")
    with pytest.raises(ValueError, match="':'"):
        MpesaConfig(
            consumer_key="bad:key",
            consumer_secret="sec",
            short_code="174379",
            passkey="pk",
        )
    with pytest.raises(ValueError, match="':'"):
        OrangeMoneyConfig(client_id="bad:id", client_secret="sec", merchant_key="mk")

    # Configs are frozen against post-init mutation
    pc = ProductConfig("sub", "user", "key")
    cfg = PyMomoSDKConfig(environment=SANDBOX, collection=pc)
    with pytest.raises(FrozenInstanceError):
        pc.callback_url = "http://169.254.169.254/meta"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        cfg.environment = "mtnghana\r\nX-Injected: evil"  # type: ignore[misc]

    # Injected httpx.Client with mismatched base_url origin is rejected
    evil = httpx.Client(base_url="https://evil.example.com")
    try:
        with pytest.raises(PyMomoSDKError, match="match configured base_url"):
            HttpClient("https://sandbox.momodeveloper.mtn.com", 30.0, client=evil)
    finally:
        evil.close()
