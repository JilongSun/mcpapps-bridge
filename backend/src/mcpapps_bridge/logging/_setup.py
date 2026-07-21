"""Logging configuration helpers.

The module initialises Python's standard ``logging`` facility once per process.
Call ``configure_logging`` as early as possible — before any other module
performs guarded ``logging.getLogger(...)`` calls — so that all loggers inherit
the correct handlers and level.
"""

from __future__ import annotations

import logging
import os
import sys
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR_ENV = "MCPAPPS_BRIDGE_LOG_DIR"
_DEFAULT_LOG_DIR = Path("backend/var/log")
_LOG_FILE_NAME = "mcpapps-bridge.log"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
_BACKUP_COUNT = 5

_FMT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"

_configured: bool = False


class LogMode(str, Enum):
    DEBUG = "debug"
    PRODUCTION = "production"


def configure_logging(mode: LogMode) -> None:
    """One-shot logging setup.  Idempotent — second call is a no-op."""
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # root is permissive; handlers control output

    formatter = logging.Formatter(fmt=_FMT, datefmt=_DATE_FMT)

    if mode is LogMode.DEBUG:
        handler: logging.Handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.DEBUG)
    else:
        log_dir = _resolve_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / _LOG_FILE_NAME
        handler = RotatingFileHandler(
            str(log_path),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setLevel(logging.INFO)

    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Keep third-party loggers quieter in production.
    if mode is LogMode.PRODUCTION:
        for noisy in ("uvicorn", "uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    _emit_startup_banner(mode)


def get_logger(name: str) -> logging.Logger:
    """Return a logger for *name*, typically ``__name__`` of the calling module."""
    return logging.getLogger(name)


# ── internal helpers ──────────────────────────────────────────────────────


def _resolve_log_dir() -> Path:
    if _LOG_DIR_ENV in os.environ:
        return Path(os.environ[_LOG_DIR_ENV])
    # Resolve relative to the *project root* (4 levels up from this file).
    project_root = Path(__file__).resolve().parents[4]
    return project_root / _DEFAULT_LOG_DIR


def _emit_startup_banner(mode: LogMode) -> None:
    logger = logging.getLogger("mcpapps-bridge")
    logger.info("── mcpapps-bridge logging initialised (mode=%s) ──", mode.value)
    if mode is LogMode.PRODUCTION:
        log_path = _resolve_log_dir() / _LOG_FILE_NAME
        logger.info("Log file: %s", log_path)
