"""Debug entry point for the bridge runtime.

This module intentionally mirrors the normal runtime entry point so debugger
launches exercise the exact same configuration and startup path as `main.py`.

Edit ``_DEBUG_CONFIG`` and ``_DEBUG_UPSTREAM`` below to change the upstream
without touching YAML or launch.json.  Set ``_DEBUG_UPSTREAM`` to ``""`` to fall
back to the normal YAML-driven selection.
"""

from __future__ import annotations

import sys

# ── Debug overrides — edit these lines ───────────────────────────────────
# Set _DEBUG_UPSTREAM to an upstream name defined in mcpapps-bridge.yaml
# to bypass the YAML default, e.g. _DEBUG_UPSTREAM = "mock_stdio"
_DEBUG_CONFIG: str | None = None  # e.g. "mcpapps-bridge.yaml"
_DEBUG_UPSTREAM = ""  # set to "" to use YAML default
_DEBUG_HTTPX_TIMEOUT: float = 0  # seconds, 0 = no timeout
# ─────────────────────────────────────────────────────────────────────────

from mcpapps_bridge.main import main  # noqa: E402

if __name__ == "__main__":
    argv = list(sys.argv[1:])
    if _DEBUG_CONFIG is not None:
        argv.extend(["--config", _DEBUG_CONFIG])
    if _DEBUG_UPSTREAM:
        argv.extend(["--upstream", _DEBUG_UPSTREAM])
    if _DEBUG_HTTPX_TIMEOUT is not None:
        argv.extend(["--httpx-timeout", str(_DEBUG_HTTPX_TIMEOUT)])
    sys.argv = [sys.argv[0], *argv]
    main()
