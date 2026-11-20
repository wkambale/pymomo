from __future__ import annotations

import re
import uuid
from urllib.parse import urlsplit

import httpx

from pymomo.exceptions import PyMoMoError

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1"})


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
