"""Idempotent stderr logging configuration owned by the server process."""

from __future__ import annotations

import logging
import sys
from enum import Enum

_FMT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"

_configured: bool = False


class LogMode(str, Enum):
    DEBUG = "debug"
    PRODUCTION = "production"


def configure_logging(mode: LogMode) -> None:
    """Configure one stderr handler; subsequent calls are no-ops."""
    global _configured
    if _configured:
        return
    _configured = True

    level = logging.DEBUG if mode is LogMode.DEBUG else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(fmt=_FMT, datefmt=_DATE_FMT)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Keep third-party loggers quieter in production.
    if mode is LogMode.PRODUCTION:
        for noisy in ("uvicorn", "uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("mabrid").info("Mabrid logging initialized (mode=%s)", mode.value)


def get_logger(name: str) -> logging.Logger:
    """Return the named standard-library logger."""
    return logging.getLogger(name)
