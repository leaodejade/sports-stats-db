"""Minimal, idempotent logging setup shared across the project."""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging once. Safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=_FORMAT,
        datefmt=_DATEFMT,
        stream=sys.stdout,
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, ensuring base configuration is in place."""
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(name)
