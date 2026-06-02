"""Collectors: fetch raw data from external sources and persist it verbatim."""

from .base import BaseCollector
from .understat_collector import UNDERSTAT_LEAGUES, UnderstatCollector

__all__ = ["BaseCollector", "UnderstatCollector", "UNDERSTAT_LEAGUES"]
