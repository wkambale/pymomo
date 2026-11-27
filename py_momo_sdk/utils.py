from __future__ import annotations

import ipaddress
import math
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote, urlsplit

import httpx

from py_momo_sdk.exceptions import PyMomoSDKError

if TYPE_CHECKING:
    from py_momo_sdk.models import AccountHolderIdType

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_ENCODED_TRAVERSAL_RE = re.compile(r"%(?:2e|2f|5c|25(?:2e|2f|5c))", re.IGNORECASE)
_DISALLOWED_IPV4_NETWORKS = (
    ipaddress.IPv4Network("100.64.0.0/10"),  # RFC 6598 CGNAT
    ipaddress.IPv4Network("192.0.0.0/24"),  # IETF protocol assignments
    ipaddress.IPv4Network("192.0.2.0/24"),  # RFC 5737 TEST-NET-1
    ipaddress.IPv4Network("192.88.99.0/24"),  # RFC 3068 6to4 relay anycast
    ipaddress.IPv4Network("198.18.0.0/15"),  # RFC 2544 benchmarking
    ipaddress.IPv4Network("198.51.100.0/24"),  # RFC 5737 TEST-NET-2
    ipaddress.IPv4Network("203.0.113.0/24"),  # RFC 5737 TEST-NET-3
)
_DISALLOWED_IPV6_NETWORKS = (
    ipaddress.IPv6Network("::/96"),  # Deprecated IPv4-compatible (::1 checked first)
    ipaddress.IPv6Network("::ffff:0:0:0/96"),  # RFC 2765 SIIT IPv4-translated
    ipaddress.IPv6Network("64:ff9b::/96"),  # RFC 6052 NAT64 well-known
    ipaddress.IPv6Network("64:ff9b:1::/48"),  # RFC 8215 NAT64 local-use
    ipaddress.IPv6Network("100::/64"),  # RFC 6666 discard-only
    ipaddress.IPv6Network("2001::/32"),  # RFC 4380 Teredo
    ipaddress.IPv6Network("2001:db8::/32"),  # RFC 3849 documentation
    ipaddress.IPv6Network("2002::/16"),  # RFC 3056 / 7526 6to4
    ipaddress.IPv6Network("fc00::/7"),  # Unique local
    ipaddress.IPv6Network("fe80::/10"),  # Link-local
    ipaddress.IPv6Network("fec0::/10"),  # Deprecated site-local
    ipaddress.IPv6Network("ff00::/8"),  # Multicast
)
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")
_COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")
_AMOUNT_RE = re.compile(r"^(?:0|[1-9][0-9]{0,17})(?:\.[0-9]+)?$")
_MSISDN_ALLOWED_CHARS_RE = re.compile(r"^[0-9+\-\s().]+$")
_ZERO_DECIMAL_CURRENCIES = frozenset(
    {"BIF", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "RWF", "UGX", "XAF", "XOF"}
)
_HEADER_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_BARE_HOST_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)
_CANONICAL_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_FORBIDDEN_SEGMENT_CHARS = frozenset({"/", "\\", "?", "#"})
_VALID_ACCOUNT_HOLDER_ID_TYPES = frozenset({"msisdn", "email", "party_code"})


def _normalize_port(scheme: str, port: int | None) -> int | None:
    """Normalize explicit default ports (443 for https, 80 for http) to None."""
    if scheme == "https" and port == 443:
        return None
    if scheme == "http" and port == 80:
        return None
    return port


def _has_malformed_authority(netloc: str) -> bool:
    """Detect malformed URL authorities (semicolons or empty trailing port colons)."""
    if ";" in netloc:
        return True
    host_port = netloc.rsplit("@", 1)[-1]
    if host_port.startswith("["):
        end = host_port.find("]")
        if end == -1:
            return True
        remainder = host_port[end + 1 :]
        return bool(
            remainder and (not remainder.startswith(":") or not remainder[1:].isdigit())
        )
    if ":" in host_port:
        _, port_part = host_port.rsplit(":", 1)
        if not port_part or not port_part.isdigit():
            return True
    return False


def _is_numeric_obfuscated_ip(host: str) -> bool:
    """Return True if host is an integer, hex, octal, or short-form IPv4 literal."""
    if not host or ":" in host:
        return False
    labels = host.split(".")
    if len(labels) > 4:
        return False
    for label in labels:
        if not label:
            return True
        if label.startswith(("0x", "0X")):
            if len(label) <= 2 or not all(
                c in "0123456789abcdefABCDEF" for c in label[2:]
            ):
                return False
        elif label.isascii() and label.isdigit():
            continue
        else:
            return False
    return True


def _is_disallowed_ipv4(addr: ipaddress.IPv4Address, *, allow_localhost: bool) -> bool:
    if addr.is_loopback:
        return not allow_localhost
    if any(addr in net for net in _DISALLOWED_IPV4_NETWORKS):
        return True
    return bool(
        addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _is_disallowed_ip_host(host: str, *, allow_localhost: bool) -> bool:
    """Return True if host resolves to a disallowed IP literal (private/metadata/obfuscated)."""
    normalized = host.strip().lower().rstrip(".")
    if not normalized:
        return True
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return not allow_localhost
    bare = (
        normalized[1:-1]
        if normalized.startswith("[") and normalized.endswith("]")
        else normalized
    )
    try:
        addr: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(bare)
    except ValueError:
        return _is_numeric_obfuscated_ip(bare)

    if isinstance(addr, ipaddress.IPv4Address):
        return _is_disallowed_ipv4(addr, allow_localhost=allow_localhost)

    if addr.ipv4_mapped is not None:
        return _is_disallowed_ipv4(addr.ipv4_mapped, allow_localhost=False)
    if addr.is_loopback:
        return not allow_localhost
    if any(addr in net for net in _DISALLOWED_IPV6_NETWORKS):
        return True
    return bool(
        addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def validate_matching_origin(configured_url: str, injected_url: str) -> None:
    """Verify that an injected HTTP client's base_url matches the configured origin."""
    cfg_split = urlsplit(configured_url)
    inj_split = urlsplit(injected_url)
    cfg_scheme = cfg_split.scheme.lower()
    inj_scheme = inj_split.scheme.lower()
    cfg_origin = (
        cfg_scheme,
        (cfg_split.hostname or "").lower(),
        _normalize_port(cfg_scheme, cfg_split.port),
    )
    inj_origin = (
        inj_scheme,
        (inj_split.hostname or "").lower(),
        _normalize_port(inj_scheme, inj_split.port),
    )
    if cfg_origin != inj_origin:
        raise PyMomoSDKError(
            "Injected HTTP client base_url must match configured base_url"
        )


def validate_base_url(base_url: str, *, allow_localhost: bool = True) -> str:
    """Validate that a base URL uses HTTPS (or localhost/127.0.0.1/::1 when permitted).

    Rejects parser-differential tricks such as userinfo credentials, leading or
    trailing whitespace, backslashes, control characters, query strings,
    fragments, private/link-local/metadata IP literals, and non-HTTP(S) schemes.

    Args:
        base_url: The base URL configured for an HTTP client.
        allow_localhost: Whether loopback hosts (``localhost``, ``127.0.0.1``, ``::1``)
            and plaintext HTTP on loopback are permitted. Set ``False`` in production.

    Returns:
        The validated base URL string.

    Raises:
        PyMomoSDKError: If the base URL is invalid or unsafe.
    """
    if (
        not isinstance(base_url, str)
        or not base_url
        or base_url != base_url.strip()
        or any(ch.isspace() for ch in base_url)
        or _CONTROL_CHAR_RE.search(base_url)
        or not base_url.isascii()
        or "\\" in base_url
    ):
        raise PyMomoSDKError("Base URL must use HTTPS")

    if "?" in base_url or "#" in base_url:
        raise PyMomoSDKError("Base URL must not contain a query string or fragment")

    try:
        split = urlsplit(base_url)
        split_port = split.port
        httpx_url = httpx.URL(base_url)
    except (ValueError, httpx.InvalidURL) as exc:
        raise PyMomoSDKError("Base URL must use HTTPS") from exc

    if _has_malformed_authority(split.netloc):
        raise PyMomoSDKError("Base URL must use HTTPS")

    scheme = split.scheme.lower()
    host = (split.hostname or "").lower()
    httpx_scheme = httpx_url.scheme.lower()
    httpx_host = httpx_url.host.lower()

    if (
        not host
        or scheme != httpx_scheme
        or host != httpx_host
        or _normalize_port(scheme, split_port)
        != _normalize_port(httpx_scheme, httpx_url.port)
    ):
        raise PyMomoSDKError("Base URL must use HTTPS")

    if not (
        scheme == "https"
        or (allow_localhost and scheme == "http" and host in _LOCALHOST_HOSTS)
    ):
        raise PyMomoSDKError("Base URL must use HTTPS")

    if _is_disallowed_ip_host(host, allow_localhost=allow_localhost):
        raise PyMomoSDKError("Base URL host is not allowed")

    if (
        split.username is not None
        or split.password is not None
        or "@" in split.netloc
        or httpx_url.username
        or httpx_url.password
    ):
        raise PyMomoSDKError("Base URL must not contain embedded credentials")

    return base_url


def validate_request_path(path: str, *, allow_query: bool = True) -> str:
    """Validate that a request path is strictly relative to the client base URL.

    Prevents absolute URLs, protocol-relative paths, or raw/percent-encoded
    dot-segment traversal from overriding the configured ``base_url`` or target
    endpoint in ``httpx``.

    Args:
        path: The relative request path.
        allow_query: Whether a query string (``?key=val``) is permitted.

    Returns:
        The validated relative request path.

    Raises:
        PyMomoSDKError: If the path is empty, absolute, protocol-relative, or
            contains control characters, whitespace, raw/encoded traversal
            segments, fragments, disallowed query strings, or backslashes.
    """
    if not isinstance(path, str):
        raise PyMomoSDKError("Request path must be a relative path starting with '/'")
    if not allow_query and "?" in path:
        raise PyMomoSDKError("Request path must not contain a query string")

    raw_path = path.split("?", 1)[0]
    decoded_path = unquote(raw_path)
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or "\\" in decoded_path
        or "#" in path
        or not path.isascii()
        or any(ch.isspace() for ch in path)
        or _CONTROL_CHAR_RE.search(path)
        or _ENCODED_TRAVERSAL_RE.search(raw_path)
        or any(seg in {".", ".."} for seg in raw_path.split("/"))
        or any(seg in {".", ".."} for seg in decoded_path.split("/"))
    ):
        raise PyMomoSDKError("Request path must be a relative path starting with '/'")

    try:
        parsed = httpx.URL(path)
    except (ValueError, httpx.InvalidURL) as exc:
        raise PyMomoSDKError(
            "Request path must be a relative path starting with '/'"
        ) from exc

    if parsed.scheme or parsed.host:
        raise PyMomoSDKError("Request path must be a relative path starting with '/'")

    return path


def generate_reference_id() -> str:
    """Return a random UUID v4 string suitable for X-Reference-Id."""
    return str(uuid.uuid4())


def normalise_msisdn(msisdn: str) -> str:
    """Validate and normalise a phone number into a clean ASCII E.164 digit string.

    Accepts ASCII digits and common formatting punctuation (``+``, ``-``,
    spaces, parentheses, dots), strips a leading ``00`` international prefix,
    and enforces E.164 length bounds (7 to 15 digits).

    Raises:
        TypeError: If ``msisdn`` is not a string.
        ValueError: If ``msisdn`` contains invalid characters or an out-of-range
            digit count.
    """
    if not isinstance(msisdn, str):
        raise TypeError("MSISDN must be a string")
    if not msisdn.strip() or not _MSISDN_ALLOWED_CHARS_RE.fullmatch(msisdn):
        raise ValueError(
            "MSISDN must contain only digits and standard phone formatting"
        )
    digits = re.sub(r"[^0-9]", "", msisdn)
    if digits.startswith("00") and len(digits) > 9:
        digits = digits[2:]
    if not (7 <= len(digits) <= 15):
        raise ValueError("MSISDN must contain between 7 and 15 digits")
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
        TypeError: If the type is not a string or ``AccountHolderIdType``.
        ValueError: If the type is not one of the supported ``AccountHolderIdType`` values.
    """
    from enum import Enum

    raw = (
        account_holder_id_type.value
        if isinstance(account_holder_id_type, Enum)
        else account_holder_id_type
    )
    if not isinstance(raw, str):
        raise TypeError("Account holder ID type must be a string")
    normalized = raw.lower()
    if normalized not in _VALID_ACCOUNT_HOLDER_ID_TYPES:
        raise ValueError(
            "Account holder ID type must be one of 'msisdn', 'email', or 'party_code'"
        )
    return normalized


def validate_amount(amount: str, *, currency: str | None = None) -> str:
    """Validate that a transaction amount is a canonical positive decimal string.

    Rejects leading zeros (such as ``"000100"``), unbounded lengths (>18 integer
    digits), more than 2 decimal places, zero/negative values, and non-zero
    fractional parts on zero-decimal currencies (when ``currency`` is provided).

    Args:
        amount: Decimal string representing the transaction amount.
        currency: Optional ISO 4217 currency code for minor-unit precision checks.

    Returns:
        The validated amount string.

    Raises:
        ValueError: If the amount is invalid, zero, negative, or violates
            minor-unit rules.
    """
    if not isinstance(amount, str) or not _AMOUNT_RE.fullmatch(amount):
        raise ValueError("Amount must be a positive decimal string")
    if "." in amount and len(amount.split(".", 1)[1]) > 2:
        raise ValueError("Amount must not have more than 2 decimal places")
    try:
        dec = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError("Amount must be a positive decimal string") from exc
    if not dec.is_finite() or dec <= 0:
        raise ValueError("Amount must be greater than zero")
    if currency is not None:
        norm_ccy = validate_currency(currency)
        if norm_ccy in _ZERO_DECIMAL_CURRENCIES and dec != dec.to_integral_value():
            raise ValueError(
                f"Amount for zero-decimal currency {norm_ccy} must not have fractional minor units"
            )
    return amount


def validate_timeout(timeout: float) -> float:
    """Validate that a network timeout is a finite positive number.

    Raises:
        ValueError: If ``timeout`` is a bool, non-finite, zero, or negative.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError("Timeout must be a positive finite number")
    timeout_float = float(timeout)
    if not math.isfinite(timeout_float) or timeout_float <= 0:
        raise ValueError("Timeout must be a positive finite number")
    return timeout_float


def validate_country_code(country: str) -> str:
    """Validate an ISO 3166-1 alpha-2 country code.

    Raises:
        ValueError: If the country code is not two ASCII letters.
    """
    if not isinstance(country, str) or not _COUNTRY_RE.fullmatch(country):
        raise ValueError("Country must be a valid two-letter ISO 3166-1 code")
    return country.upper()


def validate_header_value(
    value: str, *, field_name: str, allow_whitespace: bool = True
) -> str:
    """Validate that an HTTP header value contains only safe printable ASCII."""
    if not isinstance(value, str) or _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"{field_name} must not contain control characters")
    if not value.isascii():
        raise ValueError(f"{field_name} must contain only printable ASCII characters")
    if not allow_whitespace and any(ch.isspace() for ch in value):
        raise ValueError(f"{field_name} must not contain whitespace")
    return value


def validate_environment_name(environment: str) -> str:
    """Validate a target environment header identifier."""
    if not isinstance(environment, str) or not _HEADER_TOKEN_RE.fullmatch(environment):
        raise ValueError("Environment must be a non-empty valid identifier")
    return environment


def validate_max_retries(max_retries: int) -> int:
    """Validate that ``max_retries`` is a non-negative integer."""
    if not isinstance(max_retries, int):
        raise TypeError("max_retries must be a non-negative integer")
    if type(max_retries) is bool or max_retries < 0:
        raise ValueError("max_retries must be a non-negative integer")
    return max_retries


def validate_retry_backoff(retry_backoff: float) -> float:
    """Validate that ``retry_backoff`` is a positive finite number."""
    if isinstance(retry_backoff, bool) or not isinstance(retry_backoff, (int, float)):
        raise TypeError("retry_backoff must be a positive finite number")
    backoff_float = float(retry_backoff)
    if not math.isfinite(backoff_float) or backoff_float <= 0:
        raise ValueError("retry_backoff must be a positive finite number")
    return backoff_float


def validate_callback_url(callback_url: str, *, allow_localhost: bool = True) -> str:
    """Validate that a callback URL uses HTTPS (or localhost when permitted).

    Raises:
        ValueError: If the callback URL is not a valid HTTPS/localhost URL or
            contains embedded credentials, fragments, private/metadata IPs,
            whitespace, or control characters.
    """
    if (
        not isinstance(callback_url, str)
        or not callback_url
        or callback_url != callback_url.strip()
        or any(ch.isspace() for ch in callback_url)
        or _CONTROL_CHAR_RE.search(callback_url)
        or not callback_url.isascii()
        or "\\" in callback_url
    ):
        raise ValueError("Callback URL must use HTTPS")
    if "#" in callback_url:
        raise ValueError("Callback URL must not contain a fragment")
    try:
        split = urlsplit(callback_url)
        split_port = split.port
        httpx_url = httpx.URL(callback_url)
    except (ValueError, httpx.InvalidURL) as exc:
        raise ValueError("Callback URL must use HTTPS") from exc

    if _has_malformed_authority(split.netloc):
        raise ValueError("Callback URL must use HTTPS")

    scheme = split.scheme.lower()
    host = (split.hostname or "").lower()
    httpx_scheme = httpx_url.scheme.lower()
    if (
        not host
        or scheme != httpx_scheme
        or host != httpx_url.host.lower()
        or _normalize_port(scheme, split_port)
        != _normalize_port(httpx_scheme, httpx_url.port)
        or not (
            scheme == "https"
            or (allow_localhost and scheme == "http" and host in _LOCALHOST_HOSTS)
        )
    ):
        raise ValueError("Callback URL must use HTTPS")
    if _is_disallowed_ip_host(host, allow_localhost=allow_localhost):
        raise ValueError("Callback URL host is not allowed")
    if (
        split.username is not None
        or split.password is not None
        or "@" in split.netloc
        or httpx_url.username
        or httpx_url.password
    ):
        raise ValueError("Callback URL must not contain embedded credentials")
    return callback_url


def validate_callback_host(callback_host: str, *, allow_localhost: bool = True) -> str:
    """Validate a sandbox provider callback host (bare hostname or HTTPS URL).

    Raises:
        ValueError: If ``callback_host`` contains control characters, uses
            non-HTTPS external URLs, private/metadata IP literals, or is not a
            valid host/URL.
    """
    if (
        not isinstance(callback_host, str)
        or not callback_host
        or callback_host != callback_host.strip()
        or _CONTROL_CHAR_RE.search(callback_host)
        or not callback_host.isascii()
    ):
        raise ValueError("Callback host must be a valid hostname or HTTPS URL")
    if "://" in callback_host:
        return validate_callback_url(callback_host, allow_localhost=allow_localhost)
    if len(callback_host) > 253 or not _BARE_HOST_RE.fullmatch(callback_host):
        raise ValueError("Callback host must be a valid hostname or HTTPS URL")
    if _is_disallowed_ip_host(callback_host, allow_localhost=allow_localhost):
        raise ValueError("Callback host is not allowed")
    return callback_host


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
        or not value.strip()
        or value in (".", "..")
        or _CONTROL_CHAR_RE.search(value)
        or any(ch in value for ch in _FORBIDDEN_SEGMENT_CHARS)
    ):
        raise ValueError(f"Invalid path segment for {field_name}")
    return quote(value, safe="")


def build_basic_auth_header(api_user: str, api_key: str) -> str:
    """Return a Base64-encoded Basic authorisation header value.

    The format is 'Basic base64(api_user:api_key)'.

    Raises:
        ValueError: If ``api_user`` contains ``:`` or either credential contains
            ASCII control characters.
    """
    import base64

    validate_header_value(api_user, field_name="api_user")
    validate_header_value(api_key, field_name="api_key")
    if ":" in api_user:
        raise ValueError("API user must not contain ':'")

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
        raise ValueError("The reference ID must be a valid UUID v4")
    val = uuid.UUID(reference_id)
    if val.version != 4:
        raise ValueError("The reference ID must be a version 4 UUID")


def validate_airtel_reference_id(reference_id: str) -> str:
    """Validate an Airtel transaction reference identifier.

    Accepts canonical UUIDs as well as safe alphanumeric merchant order IDs
    (1 to 64 characters of ``A-Za-z0-9._-``), rejecting dot-segments,
    whitespace, path separators, and control characters.
    """
    if (
        not isinstance(reference_id, str)
        or not (1 <= len(reference_id) <= 64)
        or reference_id in (".", "..")
        or not _HEADER_TOKEN_RE.fullmatch(reference_id)
    ):
        raise ValueError("Invalid Airtel reference ID")
    return reference_id


_CARRIER_PREFIX_MAP: tuple[tuple[str, str, str], ...] = (
    # Uganda (256)
    ("25677", "UG", "mtn_momo"),
    ("25678", "UG", "mtn_momo"),
    ("25676", "UG", "mtn_momo"),
    ("25679", "UG", "mtn_momo"),
    ("25639", "UG", "mtn_momo"),
    ("25675", "UG", "airtel_money"),
    ("25670", "UG", "airtel_money"),
    ("25674", "UG", "airtel_money"),
    # Ghana (233)
    ("23324", "GH", "mtn_momo"),
    ("23325", "GH", "mtn_momo"),
    ("23353", "GH", "mtn_momo"),
    ("23354", "GH", "mtn_momo"),
    ("23355", "GH", "mtn_momo"),
    ("23359", "GH", "mtn_momo"),
    ("23326", "GH", "airtel_money"),
    ("23327", "GH", "airtel_money"),
    ("23356", "GH", "airtel_money"),
    ("23357", "GH", "airtel_money"),
    # Kenya (254) — 6-digit Safaricom/Airtel allocations avoid Telkom (744) & Faiba (747)
    ("254740", "KE", "mpesa"),
    ("254741", "KE", "mpesa"),
    ("254742", "KE", "mpesa"),
    ("254743", "KE", "mpesa"),
    ("254745", "KE", "mpesa"),
    ("254746", "KE", "mpesa"),
    ("254748", "KE", "mpesa"),
    ("254757", "KE", "mpesa"),
    ("254758", "KE", "mpesa"),
    ("254759", "KE", "mpesa"),
    ("254768", "KE", "mpesa"),
    ("254769", "KE", "mpesa"),
    ("254750", "KE", "airtel_money"),
    ("254751", "KE", "airtel_money"),
    ("254752", "KE", "airtel_money"),
    ("254753", "KE", "airtel_money"),
    ("254754", "KE", "airtel_money"),
    ("254755", "KE", "airtel_money"),
    ("254756", "KE", "airtel_money"),
    ("254762", "KE", "airtel_money"),
    ("25470", "KE", "mpesa"),
    ("25471", "KE", "mpesa"),
    ("25472", "KE", "mpesa"),
    ("25479", "KE", "mpesa"),
    ("25411", "KE", "mpesa"),
    ("25410", "KE", "airtel_money"),
    ("25473", "KE", "airtel_money"),
    ("25478", "KE", "airtel_money"),
    # Tanzania (255)
    ("25574", "TZ", "mpesa"),
    ("25575", "TZ", "mpesa"),
    ("25576", "TZ", "mpesa"),
    ("25568", "TZ", "airtel_money"),
    ("25569", "TZ", "airtel_money"),
    ("25578", "TZ", "airtel_money"),
    ("25579", "TZ", "airtel_money"),
    # Rwanda (250)
    ("25078", "RW", "mtn_momo"),
    ("25079", "RW", "mtn_momo"),
    ("25072", "RW", "airtel_money"),
    ("25073", "RW", "airtel_money"),
    # Zambia (260)
    ("26076", "ZM", "mtn_momo"),
    ("26096", "ZM", "mtn_momo"),
    ("26077", "ZM", "airtel_money"),
    ("26097", "ZM", "airtel_money"),
    # Malawi (265)
    ("26598", "MW", "airtel_money"),
    ("26599", "MW", "airtel_money"),
    # DRC (243)
    ("24381", "CD", "mpesa"),
    ("24382", "CD", "mpesa"),
    ("24383", "CD", "mpesa"),
    ("24397", "CD", "airtel_money"),
    ("24398", "CD", "airtel_money"),
    ("24399", "CD", "airtel_money"),
    ("24384", "CD", "orange_money"),
    ("24385", "CD", "orange_money"),
    ("24389", "CD", "orange_money"),
    # Ethiopia (251)
    ("2517", "ET", "mpesa"),
    # Cameroon (237)
    ("237650", "CM", "mtn_momo"),
    ("237651", "CM", "mtn_momo"),
    ("237652", "CM", "mtn_momo"),
    ("237653", "CM", "mtn_momo"),
    ("237654", "CM", "mtn_momo"),
    ("237655", "CM", "orange_money"),
    ("237656", "CM", "orange_money"),
    ("237657", "CM", "orange_money"),
    ("237658", "CM", "orange_money"),
    ("237659", "CM", "orange_money"),
    ("23767", "CM", "mtn_momo"),
    ("23768", "CM", "mtn_momo"),
    ("23769", "CM", "orange_money"),
    # Nigeria (234)
    ("234703", "NG", "mtn_momo"),
    ("234706", "NG", "mtn_momo"),
    ("234803", "NG", "mtn_momo"),
    ("234806", "NG", "mtn_momo"),
    ("234810", "NG", "mtn_momo"),
    ("234813", "NG", "mtn_momo"),
    ("234814", "NG", "mtn_momo"),
    ("234816", "NG", "mtn_momo"),
    ("234903", "NG", "mtn_momo"),
    ("234906", "NG", "mtn_momo"),
    ("234913", "NG", "mtn_momo"),
    ("234916", "NG", "mtn_momo"),
    ("234701", "NG", "airtel_money"),
    ("234708", "NG", "airtel_money"),
    ("234802", "NG", "airtel_money"),
    ("234808", "NG", "airtel_money"),
    ("234812", "NG", "airtel_money"),
    ("234901", "NG", "airtel_money"),
    ("234902", "NG", "airtel_money"),
    ("234904", "NG", "airtel_money"),
    ("234907", "NG", "airtel_money"),
    ("234912", "NG", "airtel_money"),
    # South Africa (27)
    ("27710", "ZA", "mtn_momo"),
    ("27717", "ZA", "mtn_momo"),
    ("27718", "ZA", "mtn_momo"),
    ("27719", "ZA", "mtn_momo"),
    ("2763", "ZA", "mtn_momo"),
    ("2768", "ZA", "mtn_momo"),
    ("2773", "ZA", "mtn_momo"),
    ("2778", "ZA", "mtn_momo"),
    ("2783", "ZA", "mtn_momo"),
    # Ivory Coast (225)
    ("22505", "CI", "mtn_momo"),
    ("22507", "CI", "orange_money"),
    ("22501", "CI", "moov_money"),
    # Senegal (221) — Wave is an OTT wallet across all SIMs; only Orange prefixes map directly
    ("22177", "SN", "orange_money"),
    ("22178", "SN", "orange_money"),
    # Benin (229)
    ("229015", "BJ", "mtn_momo"),
    ("229016", "BJ", "mtn_momo"),
    ("229019", "BJ", "mtn_momo"),
    ("22950", "BJ", "mtn_momo"),
    ("22951", "BJ", "mtn_momo"),
    ("22952", "BJ", "mtn_momo"),
    ("22953", "BJ", "mtn_momo"),
    ("22954", "BJ", "mtn_momo"),
    ("22956", "BJ", "mtn_momo"),
    ("22957", "BJ", "mtn_momo"),
    ("22959", "BJ", "mtn_momo"),
    ("22961", "BJ", "mtn_momo"),
    ("22962", "BJ", "mtn_momo"),
    ("22966", "BJ", "mtn_momo"),
    ("22967", "BJ", "mtn_momo"),
    ("22969", "BJ", "mtn_momo"),
    ("22990", "BJ", "mtn_momo"),
    ("22991", "BJ", "mtn_momo"),
    ("22996", "BJ", "mtn_momo"),
    ("22997", "BJ", "mtn_momo"),
    # Congo-Brazzaville (242)
    ("24206", "CG", "mtn_momo"),
    ("24205", "CG", "airtel_money"),
    # Liberia (231)
    ("23155", "LR", "mtn_momo"),
    ("23188", "LR", "mtn_momo"),
    ("23177", "LR", "orange_money"),
    # Guinea (224)
    ("22466", "GN", "mtn_momo"),
    ("22462", "GN", "orange_money"),
    # Eswatini (268)
    ("26876", "SZ", "mtn_momo"),
    ("26878", "SZ", "mtn_momo"),
)

# Ensure longest prefixes always match first
_SORTED_CARRIER_PREFIX_MAP: tuple[tuple[str, str, str], ...] = tuple(
    sorted(_CARRIER_PREFIX_MAP, key=lambda item: len(item[0]), reverse=True)
)


def detect_carrier_from_msisdn(
    msisdn: str,
    *,
    custom_prefixes: Any = None,
) -> tuple[str, str] | None:
    """Infer ``(country_code, provider_id)`` from an MSISDN prefix.

    Returns ``None`` if the prefix is not in the routing table. Pass
    ``custom_prefixes`` (mapping prefix string to ``(country_code, provider_id)``)
    to override ported numbers or OTT wallets such as Wave.
    """
    if not isinstance(msisdn, str):
        raise TypeError("MSISDN must be a string")
    digits = re.sub(r"[^0-9]", "", msisdn).removeprefix("00")
    if not (10 <= len(digits) <= 15):
        return None
    if custom_prefixes is not None:
        for prefix, target in sorted(
            custom_prefixes.items(), key=lambda kv: len(str(kv[0])), reverse=True
        ):
            clean_prefix = re.sub(r"[^0-9]", "", str(prefix)).removeprefix("00")
            if clean_prefix and digits.startswith(clean_prefix):
                return (str(target[0]), str(target[1]))
    for prefix, country, provider in _SORTED_CARRIER_PREFIX_MAP:
        if digits.startswith(prefix):
            return (country, provider)
    return None


def _validate_polling_params(
    interval: float, backoff: float, max_interval: float
) -> tuple[float, float, float]:
    for val in (interval, backoff, max_interval):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise TypeError("Polling interval, backoff, and max_interval must be valid")
    interval_f = float(interval)
    backoff_f = float(backoff)
    max_interval_f = float(max_interval)
    if (
        not math.isfinite(interval_f)
        or not math.isfinite(backoff_f)
        or not math.isfinite(max_interval_f)
        or interval_f <= 0
        or backoff_f < 1.0
        or max_interval_f <= 0
    ):
        raise ValueError("Polling interval, backoff, and max_interval must be valid")
    return interval_f, backoff_f, max_interval_f


def _extract_status_str(result: Any) -> str | None:
    """Extract an uppercase status string from a model, enum, or mapping."""
    from enum import Enum

    raw = (
        result.get("status")
        if isinstance(result, dict)
        else getattr(result, "status", None)
    )
    if isinstance(raw, Enum):
        raw = raw.value
    return raw.strip().upper() if isinstance(raw, str) else None


def _is_result_pending(result: Any) -> bool:
    """Determine whether a polled transaction result is still pending."""
    if hasattr(result, "is_pending"):
        attr = result.is_pending
        return bool(attr() if callable(attr) else attr)
    return _extract_status_str(result) == "PENDING"


def _raise_if_result_failed(result: Any, *, reference_id: str | None = None) -> None:
    """Raise TransactionFailedError when a settled result represents a failure."""
    from py_momo_sdk.exceptions import TransactionFailedError

    is_failed = False
    if hasattr(result, "is_failed"):
        attr = result.is_failed
        is_failed = bool(attr() if callable(attr) else attr)
    else:
        is_failed = _extract_status_str(result) == "FAILED"

    if is_failed:
        result_ref = (
            result.get("reference_id")
            if isinstance(result, dict)
            else getattr(result, "reference_id", None)
            or getattr(result, "external_id", None)
        )
        ref = reference_id or result_ref
        reason = (
            result.get("reason")
            if isinstance(result, dict)
            else getattr(result, "reason", None)
        )
        raise TransactionFailedError(
            reference_id=str(ref or "unknown"),
            reason=str(reason) if reason is not None else None,
        )


def _jittered_poll_delay(delay: float, max_interval: float) -> float:
    import secrets

    max_jitter_ms = int(min(250.0, delay * 100.0))
    jitter = secrets.randbelow(max_jitter_ms) / 1000.0 if max_jitter_ms > 0 else 0.0
    return min(delay + jitter, max_interval)


def wait_for_settlement(
    poll_fn: Any,
    *,
    timeout: float = 60.0,
    interval: float = 2.0,
    backoff: float = 1.5,
    max_interval: float = 10.0,
    sleep_fn: Any = None,
    raise_on_failed: bool = False,
    reference_id: str | None = None,
) -> Any:
    """Poll ``poll_fn`` until a transaction leaves the pending state.

    Args:
        poll_fn: Zero-argument callable returning an object or dict with
            ``is_pending()`` or ``status``.
        timeout: Maximum total wait time in seconds.
        interval: Initial sleep interval between polls in seconds.
        backoff: Multiplier applied to ``interval`` after each pending poll.
        max_interval: Maximum sleep interval between polls in seconds.
        sleep_fn: Optional sleep callable (defaults to ``time.sleep``).
        raise_on_failed: When ``True``, raise ``TransactionFailedError`` if the
            settled result has failed status.
        reference_id: Optional transaction reference ID attached to raised
            ``TransactionFailedError`` or timeout ``PyMomoSDKError`` instances.

    Returns:
        The settled status object.

    Raises:
        PyMomoSDKError: If ``timeout`` expires while the transaction is still
            pending.
        TransactionFailedError: If ``raise_on_failed=True`` and the transaction
            settled to a failed state.
    """
    import time

    timeout_f = validate_timeout(timeout)
    interval_f, backoff_f, max_interval_f = _validate_polling_params(
        interval, backoff, max_interval
    )

    sleeper = sleep_fn or time.sleep
    deadline = time.monotonic() + timeout_f
    delay = min(interval_f, max_interval_f)

    while True:
        result = poll_fn()
        if not _is_result_pending(result):
            if raise_on_failed:
                _raise_if_result_failed(result, reference_id=reference_id)
            return result
        remaining = deadline - time.monotonic()
        sleep_for = _jittered_poll_delay(delay, max_interval_f)
        if remaining <= 0 or sleep_for >= remaining:
            raise PyMomoSDKError(
                "Transaction settlement polling timed out",
                reference_id=reference_id,
            )
        sleeper(sleep_for)
        delay = min(delay * backoff_f, max_interval_f)


async def async_wait_for_settlement(
    poll_fn: Any,
    *,
    timeout: float = 60.0,
    interval: float = 2.0,
    backoff: float = 1.5,
    max_interval: float = 10.0,
    sleep_fn: Any = None,
    raise_on_failed: bool = False,
    reference_id: str | None = None,
) -> Any:
    """Asynchronously poll ``poll_fn`` until a transaction leaves pending state."""
    import asyncio
    import time

    timeout_f = validate_timeout(timeout)
    interval_f, backoff_f, max_interval_f = _validate_polling_params(
        interval, backoff, max_interval
    )

    sleeper = sleep_fn or asyncio.sleep
    deadline = time.monotonic() + timeout_f
    delay = min(interval_f, max_interval_f)

    while True:
        result = await poll_fn()
        if not _is_result_pending(result):
            if raise_on_failed:
                _raise_if_result_failed(result, reference_id=reference_id)
            return result
        remaining = deadline - time.monotonic()
        sleep_for = _jittered_poll_delay(delay, max_interval_f)
        if remaining <= 0 or sleep_for >= remaining:
            raise PyMomoSDKError(
                "Transaction settlement polling timed out",
                reference_id=reference_id,
            )
        await sleeper(sleep_for)
        delay = min(delay * backoff_f, max_interval_f)
