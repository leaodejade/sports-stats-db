"""Collector for Jeff Sackmann's tennis datasets.

Fetches CSV files from GitHub repositories:
- ATP: https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/
- WTA: https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/

Converts downloaded CSV rows to lists of dicts to be cached as JSON by BaseCollector.
"""

from __future__ import annotations

import csv
from io import StringIO
import urllib.request
from typing import Any, List, Dict

from .base import BaseCollector

class TennisSackmannCollector(BaseCollector):
    source_name = "sackmann"

    BASE_URLS = {
        "ATP": "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/",
        "WTA": "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master/",
    }

    def _fetch_csv_as_dicts(self, url: str) -> List[Dict[str, Any]]:
        """Downloads a CSV and converts it to a list of dicts."""
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            content = response.read().decode('utf-8')

        reader = csv.DictReader(StringIO(content))
        return list(reader)

    def fetch_matches(self, tour: str, season: str) -> List[Dict[str, Any]]:
        """Fetches match results for a given tour (ATP/WTA) and season (year)."""
        tour = tour.upper()
        if tour not in self.BASE_URLS:
            raise ValueError(f"Invalid tour: {tour}")

        entity = f"matches_{tour.lower()}"
        key = str(season)
        url = f"{self.BASE_URLS[tour]}{tour.lower()}_matches_{season}.csv"

        return self._fetch_with_cache(entity, key, lambda: self._fetch_csv_as_dicts(url))

    def fetch_players(self, tour: str) -> List[Dict[str, Any]]:
        """Fetches the players catalog for a given tour."""
        tour = tour.upper()
        entity = f"players_{tour.lower()}"
        key = "all"
        url = f"{self.BASE_URLS[tour]}{tour.lower()}_players.csv"

        return self._fetch_with_cache(entity, key, lambda: self._fetch_csv_as_dicts(url))

    def fetch_rankings(self, tour: str, decade: str) -> List[Dict[str, Any]]:
        """Fetches rankings for a given tour and decade (e.g. '20s', '10s').

        Sackmann breaks rankings into decade files. Example: atp_rankings_20s.csv
        """
        tour = tour.upper()
        entity = f"rankings_{tour.lower()}"
        key = str(decade)
        url = f"{self.BASE_URLS[tour]}{tour.lower()}_rankings_{decade}.csv"

        return self._fetch_with_cache(entity, key, lambda: self._fetch_csv_as_dicts(url))
