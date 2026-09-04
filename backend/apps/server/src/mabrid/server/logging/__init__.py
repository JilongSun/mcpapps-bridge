"""Process logging for the Mabrid server.

Both debug and production modes write to stderr so deployment environments own collection,
rotation, and retention. The server configures levels and formatting only.
"""

from __future__ import annotations

from ._setup import LogMode, configure_logging, get_logger

__all__ = ["LogMode", "configure_logging", "get_logger"]
