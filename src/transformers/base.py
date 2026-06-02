"""Type-coercion and normalisation helpers shared by transformers.

Understat returns almost everything as strings (``"29.5"``, ``"34"``), so these
helpers convert defensively: anything unparseable becomes ``None`` rather than
raising, which keeps ingestion resilient to occasional dirty rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def to_float(value: Any) -> Optional[float]:
    """Best-effort conversion to ``float``; returns ``None`` on failure/empty."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> Optional[int]:
    """Best-effort conversion to ``int`` (via float to tolerate ``"3.0"``)."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_bool_home(h_a: Any) -> Optional[bool]:
    """Map Understat's ``h``/``a`` flag to a boolean ``is_home``."""
    if h_a is None:
        return None
    text = str(h_a).strip().lower()
    if text in ("h", "home"):
        return True
    if text in ("a", "away"):
        return False
    return None


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse Understat datetime strings, trying a few known formats."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def clean_str(value: Any) -> Optional[str]:
    """Trim whitespace and collapse empty strings to ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_ppda(value: Any) -> Optional[float]:
    """Understat ``ppda`` may be a number or ``{"att": x, "def": y}``.

    Returns ``att / def`` (passes allowed per defensive action), or the raw
    number when already flattened.
    """
    if isinstance(value, dict):
        att = to_float(value.get("att"))
        deff = to_float(value.get("def"))
        if att is None or not deff:
            return None
        return att / deff
    return to_float(value)
