from __future__ import annotations

import math
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit

import httpx

from py_momo_sdk.exceptions import PyMomoSDKError

if TYPE_CHECKING:
    from py_momo_sdk.models import AccountHolderIdType

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1"})
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")
_COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")
_AMOUNT_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
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
        PyMomoSDKError: If the base URL is invalid or does not use HTTPS.
    """
    if (
        not isinstance(base_url, str)
        or not base_url
        or base_url != base_url.strip()
        or any(ch.isspace() for ch in base_url)
        or _CONTROL_CHAR_RE.search(base_url)
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

    scheme = split.scheme.lower()
    host = (split.hostname or "").lower()
    httpx_scheme = httpx_url.scheme.lower()
    httpx_host = httpx_url.host.lower()

    if (
        not host
        or scheme != httpx_scheme
        or host != httpx_host
        or split_port != httpx_url.port
    ):
        raise PyMomoSDKError("Base URL must use HTTPS")

    if not (scheme == "https" or (scheme == "http" and host in _LOCALHOST_HOSTS)):
        raise PyMomoSDKError("Base URL must use HTTPS")

    if (
        split.username is not None
        or split.password is not None
        or "@" in split.netloc
        or httpx_url.username
        or httpx_url.password
    ):
        raise PyMomoSDKError("Base URL must not contain embedded credentials")

    if split.query or split.fragment:
        raise PyMomoSDKError("Base URL must not contain a query string or fragment")

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
        PyMomoSDKError: If the path is empty, absolute, protocol-relative, or
            contains control characters, whitespace, dot-segments, query/fragment,
            or backslashes.
    """
    raw_path = path.split("?", 1)[0] if isinstance(path, str) else ""
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or "#" in path
        or any(ch.isspace() for ch in path)
        or _CONTROL_CHAR_RE.search(path)
        or any(seg in {".", ".."} for seg in raw_path.split("/"))
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
    """Strip non-digit characters and return a clean ASCII MSISDN string.

    Does not validate the number against any country's numbering plan.
    Callers are responsible for providing a valid number.

    Raises:
        TypeError: If ``msisdn`` is not a string.
        ValueError: If no ASCII digits remain after stripping non-digit characters.
    """
    if not isinstance(msisdn, str):
        raise TypeError("MSISDN must be a string")
    digits = re.sub(r"[^0-9]", "", msisdn)
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


def validate_amount(amount: str) -> str:
    """Validate that a transaction amount is a positive finite decimal string.

    Args:
        amount: Decimal string representing the transaction amount.

    Returns:
        The validated amount string.

    Raises:
        ValueError: If the amount is non-numeric, non-finite, zero, or negative.
    """
    if not isinstance(amount, str) or not _AMOUNT_RE.fullmatch(amount):
        raise ValueError("Amount must be a positive decimal string")
    try:
        dec = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError("Amount must be a positive decimal string") from exc
    if not dec.is_finite() or dec <= 0:
        raise ValueError("Amount must be greater than zero")
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


def validate_header_value(value: str, *, field_name: str) -> str:
    """Validate that an HTTP header value contains no ASCII control characters."""
    if not isinstance(value, str) or _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"{field_name} must not contain control characters")
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


def validate_callback_url(callback_url: str) -> str:
    """Validate that a callback URL uses HTTPS (or localhost/127.0.0.1 for testing).

    Raises:
        ValueError: If the callback URL is not a valid HTTPS/localhost URL or
            contains embedded credentials, fragments, whitespace, or control characters.
    """
    if (
        not isinstance(callback_url, str)
        or not callback_url
        or callback_url != callback_url.strip()
        or any(ch.isspace() for ch in callback_url)
        or _CONTROL_CHAR_RE.search(callback_url)
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

    scheme = split.scheme.lower()
    host = (split.hostname or "").lower()
    if (
        not host
        or scheme != httpx_url.scheme.lower()
        or host != httpx_url.host.lower()
        or split_port != httpx_url.port
        or not (scheme == "https" or (scheme == "http" and host in _LOCALHOST_HOSTS))
    ):
        raise ValueError("Callback URL must use HTTPS")
    if (
        split.username is not None
        or split.password is not None
        or "@" in split.netloc
        or httpx_url.username
        or httpx_url.password
    ):
        raise ValueError("Callback URL must not contain embedded credentials")
    if split.fragment:
        raise ValueError("Callback URL must not contain a fragment")
    return callback_url


def validate_callback_host(callback_host: str) -> str:
    """Validate a sandbox provider callback host (bare hostname or HTTPS URL).

    Raises:
        ValueError: If ``callback_host`` contains control characters, uses
            non-HTTPS external URLs, or is not a valid host/URL.
    """
    if (
        not isinstance(callback_host, str)
        or not callback_host
        or callback_host != callback_host.strip()
        or _CONTROL_CHAR_RE.search(callback_host)
    ):
        raise ValueError("Callback host must be a valid hostname or HTTPS URL")
    if "://" in callback_host:
        return validate_callback_url(callback_host)
    if not _BARE_HOST_RE.fullmatch(callback_host):
        raise ValueError("Callback host must be a valid hostname or HTTPS URL")
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
        raise ValueError(f"The reference ID must be a valid UUID v4: {reference_id}")
    try:
        val = uuid.UUID(reference_id)
    except ValueError as exc:
        raise ValueError(
            f"The reference ID must be a valid UUID v4: {reference_id}"
        ) from exc
    if val.version != 4:
        raise ValueError(f"The reference ID must be a version 4 UUID: {reference_id}")


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
        raise ValueError(f"Invalid Airtel reference ID: {reference_id!r}")
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
    ("23354", "GH", "mtn_momo"),
    ("23355", "GH", "mtn_momo"),
    ("23359", "GH", "mtn_momo"),
    ("23327", "GH", "airtel_money"),
    ("23357", "GH", "airtel_money"),
    ("23326", "GH", "airtel_money"),
    # Kenya (254)
    ("25470", "KE", "mpesa"),
    ("25471", "KE", "mpesa"),
    ("25472", "KE", "mpesa"),
    ("25474", "KE", "mpesa"),
    ("25479", "KE", "mpesa"),
    ("25411", "KE", "mpesa"),
    ("25473", "KE", "airtel_money"),
    ("25478", "KE", "airtel_money"),
    # Rwanda (250)
    ("25078", "RW", "mtn_momo"),
    ("25079", "RW", "mtn_momo"),
    ("25072", "RW", "airtel_money"),
    ("25073", "RW", "airtel_money"),
    # Ivory Coast (225)
    ("22505", "CI", "mtn_momo"),
    ("22507", "CI", "orange_money"),
    ("22501", "CI", "moov_money"),
    # Senegal (221)
    ("22177", "SN", "orange_money"),
    ("22178", "SN", "orange_money"),
    ("22176", "SN", "wave"),
    ("22170", "SN", "wave"),
)


def detect_carrier_from_msisdn(msisdn: str) -> tuple[str, str] | None:
    """Infer ``(country_code, provider_id)`` from an MSISDN prefix.

    Returns ``None`` if the prefix is not in the built-in routing table. Callers
    should allow explicit provider overrides for ported numbers.
    """
    if not isinstance(msisdn, str):
        raise TypeError("MSISDN must be a string")
    digits = re.sub(r"[^0-9]", "", msisdn).removeprefix("00")
    if not (10 <= len(digits) <= 15):
        return None
    for prefix, country, provider in _CARRIER_PREFIX_MAP:
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


def wait_for_settlement(
    poll_fn: Any,
    *,
    timeout: float = 60.0,
    interval: float = 2.0,
    backoff: float = 1.5,
    max_interval: float = 10.0,
    sleep_fn: Any = None,
) -> Any:
    """Poll ``poll_fn`` until a transaction leaves the pending state.

    Args:
        poll_fn: Zero-argument callable returning an object with ``is_pending()``
            or ``status``.
        timeout: Maximum total wait time in seconds.
        interval: Initial sleep interval between polls in seconds.
        backoff: Multiplier applied to ``interval`` after each pending poll.
        max_interval: Maximum sleep interval between polls in seconds.
        sleep_fn: Optional sleep callable (defaults to ``time.sleep``).

    Returns:
        The settled status object.

    Raises:
        PyMomoSDKError: If ``timeout`` expires while the transaction is still
            pending.
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
        is_pending = (
            result.is_pending()
            if hasattr(result, "is_pending")
            else getattr(result, "status", None) == "PENDING"
        )
        if not is_pending:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PyMomoSDKError("Transaction settlement polling timed out")
        sleeper(min(delay, remaining))
        delay = min(delay * backoff_f, max_interval_f)


async def async_wait_for_settlement(
    poll_fn: Any,
    *,
    timeout: float = 60.0,
    interval: float = 2.0,
    backoff: float = 1.5,
    max_interval: float = 10.0,
    sleep_fn: Any = None,
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
        is_pending = (
            result.is_pending()
            if hasattr(result, "is_pending")
            else getattr(result, "status", None) == "PENDING"
        )
        if not is_pending:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PyMomoSDKError("Transaction settlement polling timed out")
        await sleeper(min(delay, remaining))
        delay = min(delay * backoff_f, max_interval_f)
