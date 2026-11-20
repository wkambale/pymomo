from __future__ import annotations

import re
import uuid
from urllib.parse import quote, urlsplit

import httpx

from pymomo.exceptions import PyMoMoError
from pymomo.models import AccountHolderIdType

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1"})
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")
_CANONICAL_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_FORBIDDEN_SEGMENT_CHARS = frozenset({"/", "\\", "?", "#"})


def validate_base_url(base_url: str) -> str:
    """Validate that a base URL uses HTTPS (except localhost/127.0.0.1).

    Rejects parser-differential tricks such as userinfo credentials, leading or
    trailing whitespace, backslashes, control characters, query strings,
    fragments, and non-HTTP(S) schemes.

    Args:
        base_url: The base URL configured for an HTTP client.

    Returns:
        The validated base URL string.

    Raises:
        PyMoMoError: If the base URL is invalid or does not use HTTPS.
    """
    if (
        not isinstance(base_url, str)
        or not base_url
        or base_url != base_url.strip()
        or _CONTROL_CHAR_RE.search(base_url)
        or "\\" in base_url
    ):
        raise PyMoMoError("Base URL must use HTTPS")

    try:
        split = urlsplit(base_url)
        httpx_url = httpx.URL(base_url)
    except (ValueError, httpx.InvalidURL) as exc:
        raise PyMoMoError("Base URL must use HTTPS") from exc

    scheme = split.scheme.lower()
    host = (split.hostname or "").lower()
    httpx_scheme = httpx_url.scheme.lower()
    httpx_host = httpx_url.host.lower()

    if not host or scheme != httpx_scheme or host != httpx_host:
        raise PyMoMoError("Base URL must use HTTPS")

    if not (scheme == "https" or (scheme == "http" and host in _LOCALHOST_HOSTS)):
        raise PyMoMoError("Base URL must use HTTPS")

    if (
        split.username is not None
        or split.password is not None
        or "@" in split.netloc
        or httpx_url.username
        or httpx_url.password
    ):
        raise PyMoMoError("Base URL must not contain embedded credentials")

    if split.query or split.fragment:
        raise PyMoMoError("Base URL must not contain a query string or fragment")

    return base_url


def validate_request_path(path: str) -> str:
    """Validate that a request path is strictly relative to the client base URL.

    Prevents absolute URLs or protocol-relative paths from overriding the
    configured ``base_url`` in ``httpx``.

    Args:
        path: The relative request path.

    Returns:
        The validated relative request path.

    Raises:
        PyMoMoError: If the path is empty, absolute, protocol-relative, or
            contains control characters or backslashes.
    """
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or _CONTROL_CHAR_RE.search(path)
    ):
        raise PyMoMoError("Request path must be a relative path starting with '/'")

    try:
        parsed = httpx.URL(path)
    except (ValueError, httpx.InvalidURL) as exc:
        raise PyMoMoError(
            "Request path must be a relative path starting with '/'"
        ) from exc

    if parsed.scheme or parsed.host:
        raise PyMoMoError("Request path must be a relative path starting with '/'")

    return path


def generate_reference_id() -> str:
    """Return a random UUID v4 string suitable for X-Reference-Id."""
    return str(uuid.uuid4())


def normalise_msisdn(msisdn: str) -> str:
    """Strip non-digit characters and return a clean MSISDN string.

    Does not validate the number against any country's numbering plan.
    Callers are responsible for providing a valid number.

    Raises:
        ValueError: If no digits remain after stripping non-digit characters.
    """
    digits = re.sub(r"\D", "", msisdn)
    if not digits:
        raise ValueError("MSISDN must contain at least one digit")
    return digits


def validate_currency(currency: str) -> str:
    """Validate an ISO 4217 three-letter currency code.

    Args:
        currency: Currency code string.

    Returns:
        The validated uppercase three-letter currency code.

    Raises:
        ValueError: If the currency is not a three-letter ASCII alphabetic code.
    """
    if not isinstance(currency, str) or not _CURRENCY_RE.fullmatch(currency):
        raise ValueError("Currency must be a valid three-letter ISO 4217 code")
    return currency.upper()


def validate_account_holder_id_type(
    account_holder_id_type: str | AccountHolderIdType,
) -> str:
    """Validate and normalize an account holder ID type.

    Args:
        account_holder_id_type: Account holder type enum or string.

    Returns:
        The canonical lowercase type value (``msisdn``, ``email``, or ``party_code``).

    Raises:
        ValueError: If the type is not one of the supported ``AccountHolderIdType`` values.
    """
    if isinstance(account_holder_id_type, AccountHolderIdType):
        return account_holder_id_type.value
    if not isinstance(account_holder_id_type, str):
        raise TypeError("Account holder ID type must be a string")
    normalized = account_holder_id_type.lower()
    try:
        return AccountHolderIdType(normalized).value
    except ValueError as exc:
        raise ValueError(
            "Account holder ID type must be one of 'msisdn', 'email', or 'party_code'"
        ) from exc


def encode_path_segment(value: str, *, field_name: str = "value") -> str:
    """Validate and percent-encode a single URL path segment.

    Rejects empty values, dot-segments (``.``, ``..``), path separators, query
    or fragment delimiters, and ASCII control characters.

    Args:
        value: Raw path segment value.
        field_name: Name of the field for error messages.

    Returns:
        The percent-encoded path segment.

    Raises:
        ValueError: If the value is empty or contains unsafe path characters.
    """
    if (
        not isinstance(value, str)
        or not value
        or value in (".", "..")
        or _CONTROL_CHAR_RE.search(value)
        or any(ch in value for ch in _FORBIDDEN_SEGMENT_CHARS)
    ):
        raise ValueError(f"Invalid path segment for {field_name}")
    return quote(value, safe="")


def build_basic_auth_header(api_user: str, api_key: str) -> str:
    """Return a Base64-encoded Basic authorisation header value.

    The format is 'Basic base64(api_user:api_key)'.
    """
    import base64

    raw = f"{api_user}:{api_key}"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def validate_reference_id(reference_id: str) -> None:
    """Validate that the given string is a canonical hyphenated UUID v4.

    Raises:
        ValueError: If the string is not a canonical UUID v4 or is not version 4.
    """
    if not isinstance(reference_id, str) or not _CANONICAL_UUID_RE.fullmatch(
        reference_id
    ):
        raise ValueError(f"The reference ID must be a valid UUID v4: {reference_id}")
    try:
        val = uuid.UUID(reference_id)
    except ValueError as exc:
        raise ValueError(
            f"The reference ID must be a valid UUID v4: {reference_id}"
        ) from exc
    if val.version != 4:
        raise ValueError(f"The reference ID must be a version 4 UUID: {reference_id}")
