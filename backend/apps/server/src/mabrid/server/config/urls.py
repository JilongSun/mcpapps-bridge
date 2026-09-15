"""Validated deployment URLs advertised to external MCP clients."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
ENDPOINT_SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


def normalize_advertised_base_url(value: str) -> str:
    raw = urlsplit(value)
    if raw.scheme not in {"http", "https"} or raw.hostname is None:
        raise ValueError("advertisedBaseUrl must be an HTTP(S) origin")
    if raw.username is not None or raw.password is not None:
        raise ValueError("advertisedBaseUrl must not contain user information")
    if raw.path not in {"", "/"}:
        raise ValueError("advertisedBaseUrl must not contain a path")
    if raw.query:
        raise ValueError("advertisedBaseUrl must not contain a query")
    if raw.fragment:
        raise ValueError("advertisedBaseUrl must not contain a fragment")
    try:
        url = HTTP_URL_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise ValueError("advertisedBaseUrl must be an HTTP(S) origin") from exc
    return str(url).rstrip("/")


def build_advertised_mcp_url(base_url: str, endpoint_slug: str) -> str:
    if ENDPOINT_SLUG_PATTERN.fullmatch(endpoint_slug) is None:
        raise ValueError(f"Invalid endpoint slug: {endpoint_slug}")
    origin = urlsplit(normalize_advertised_base_url(base_url))
    return urlunsplit((origin.scheme, origin.netloc, f"/mcp/{endpoint_slug}", "", ""))
