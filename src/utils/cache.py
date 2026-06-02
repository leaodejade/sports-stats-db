"""File-based storage of raw JSON payloads.

Doubles as a primitive local cache: a payload saved under
``<raw_dir>/<source>/<entity>/<key>.json`` can be reloaded instead of issuing
a new network request. This keeps the project gentle on the data source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .logging import get_logger

logger = get_logger(__name__)


def _safe_name(name: str) -> str:
    """Turn an arbitrary key into a filesystem-safe filename component."""
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(name))


def raw_path_for(raw_dir: Path | str, source: str, entity: str, key: str) -> Path:
    """Compute the deterministic path for a raw payload."""
    return Path(raw_dir) / _safe_name(source) / _safe_name(entity) / f"{_safe_name(key)}.json"


def save_raw(
    raw_dir: Path | str,
    source: str,
    entity: str,
    key: str,
    payload: Any,
) -> Path:
    """Persist ``payload`` as pretty JSON and return the file path."""
    path = raw_path_for(raw_dir, source, entity, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    logger.debug("Saved raw payload: %s", path)
    return path


def load_raw(
    raw_dir: Path | str,
    source: str,
    entity: str,
    key: str,
) -> Optional[Any]:
    """Return a previously saved payload, or ``None`` if it does not exist."""
    path = raw_path_for(raw_dir, source, entity, key)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:  # corrupt cache -> ignore
        logger.warning("Could not read cached payload %s: %s", path, exc)
        return None
