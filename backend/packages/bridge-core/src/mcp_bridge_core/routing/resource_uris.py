"""Aggregate public resource URI generation and MCP Apps metadata rewriting.

Public URI generation is deterministic, but route authority remains the exact per-session map in
the aggregate router. These helpers never decode a public URI to select an upstream binding.
"""

from __future__ import annotations

import re
from base64 import urlsafe_b64encode
from hashlib import sha256
from typing import Any

from pydantic import AnyUrl


def public_resource_uri(namespace: str, upstream_uri: str) -> str:
    if upstream_uri.startswith("ui://"):
        digest = sha256(upstream_uri.encode("utf-8")).digest()[:18]
        token = urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return f"ui://{namespace}/{token}"
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", upstream_uri) is None:
        raise ValueError(f"Upstream resource URI has no valid scheme: {upstream_uri}")
    return f"{namespace}+{upstream_uri}"


def canonical_uri(uri: str) -> str:
    return str(AnyUrl(uri))


def rewrite_ui_metadata(
    metadata: dict[str, Any],
    public_ui_uri: str | None,
) -> dict[str, Any]:
    rewritten = dict(metadata)
    if public_ui_uri is None:
        return rewritten
    if "ui" in rewritten:
        rewritten["ui"] = (
            {**rewritten["ui"], "resourceUri": public_ui_uri}
            if isinstance(rewritten["ui"], dict)
            else public_ui_uri
        )
    if "ui/resourceUri" in rewritten:
        rewritten["ui/resourceUri"] = public_ui_uri
    if "openai/outputTemplate" in rewritten:
        rewritten["openai/outputTemplate"] = public_ui_uri
    if "openai/resourceUri" in rewritten:
        rewritten["openai/resourceUri"] = public_ui_uri
    if isinstance(rewritten.get("openai"), dict):
        openai = dict(rewritten["openai"])
        if "resourceUri" in openai:
            openai["resourceUri"] = public_ui_uri
        if "outputTemplate" in openai:
            openai["outputTemplate"] = public_ui_uri
        rewritten["openai"] = openai
    nested_meta = rewritten.get("_meta")
    if isinstance(nested_meta, dict):
        rewritten_nested_meta = dict(nested_meta)
        if "ui" in rewritten_nested_meta:
            rewritten_nested_meta["ui"] = (
                {**rewritten_nested_meta["ui"], "resourceUri": public_ui_uri}
                if isinstance(rewritten_nested_meta["ui"], dict)
                else public_ui_uri
            )
        if "ui/resourceUri" in rewritten_nested_meta:
            rewritten_nested_meta["ui/resourceUri"] = public_ui_uri
        rewritten["_meta"] = rewritten_nested_meta
    return rewritten
