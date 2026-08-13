"""HTTP(S) endpoint checks for http and hermes agents."""

from __future__ import annotations

from urllib.parse import urlparse


class UnsafeEndpoint(ValueError):
    """Raised when an agent endpoint is not safe to fetch."""


def validate_http_endpoint(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        raise UnsafeEndpoint("endpoint URL is required")
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeEndpoint("endpoint must use http or https")
    if parsed.username or parsed.password:
        raise UnsafeEndpoint("endpoint must not contain credentials")
    if not parsed.hostname:
        raise UnsafeEndpoint("endpoint host is required")
    return cleaned.rstrip("/")
