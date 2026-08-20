"""Application logging setup for the mcpapps bridge runtime.

Provides ``configure_logging`` to initialise the logging system early in the
startup sequence.  Two modes are supported:

* **debug** – console (stderr) output at DEBUG level, intended for
  ``debug_main.py``.
* **production** – rotating file output at INFO level, no console noise.
  Logs are written to ``backend/var/log/mcpapps-bridge.log`` by default.

Set the environment variable ``MCPAPPS_BRIDGE_LOG_DIR`` to override the log
directory (useful for Docker volume mounts).
"""

from __future__ import annotations

from ._setup import LogMode, configure_logging, get_logger

__all__ = ["LogMode", "configure_logging", "get_logger"]
