"""Abstract collector: shared raw-saving, caching and rate-limiting behaviour.

A collector's only job is to *fetch raw data and persist it untouched*. Parsing
lives in transformers; persistence to the relational model lives in services.
New sources (FBref, etc.) subclass this and implement their own fetch methods.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from ..utils.cache import load_raw, save_raw
from ..utils.config import Settings, get_settings
from ..utils.logging import get_logger


class BaseCollector(ABC):
    """Base class providing cache lookup, raw persistence and politeness."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        request_delay: Optional[float] = None,
        cache_enabled: Optional[bool] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.raw_dir: Path = self.settings.raw_path
        self.request_delay = (
            request_delay
            if request_delay is not None
            else self.settings.understat_request_delay
        )
        self.cache_enabled = (
            cache_enabled if cache_enabled is not None else self.settings.cache_enabled
        )
        self.logger = get_logger(self.__class__.__name__)

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Identifier used for raw-file folders and the data_sources table."""

    # -- infrastructure shared by all collectors ---------------------------
    def _cached(self, entity: str, key: str) -> Optional[Any]:
        if not self.cache_enabled:
            return None
        payload = load_raw(self.raw_dir, self.source_name, entity, key)
        if payload is not None:
            self.logger.debug("Cache hit: %s/%s/%s", self.source_name, entity, key)
        return payload

    def _persist(self, entity: str, key: str, payload: Any) -> Path:
        return save_raw(self.raw_dir, self.source_name, entity, key, payload)

    def _sleep(self) -> None:
        if self.request_delay and self.request_delay > 0:
            time.sleep(self.request_delay)

    def _fetch_with_cache(self, entity: str, key: str, fetch_fn) -> Any:
        """Return cached payload if present, else fetch, persist and rate-limit."""
        cached = self._cached(entity, key)
        if cached is not None:
            return cached
        self.logger.info("Fetching %s/%s/%s", self.source_name, entity, key)
        payload = fetch_fn()
        self._persist(entity, key, payload)
        self._sleep()
        return payload
