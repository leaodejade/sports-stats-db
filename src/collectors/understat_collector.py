"""Collector for Understat, backed by the ``understatapi`` package.

Reference: https://github.com/collinb9/understatAPI

Only the lightweight league-level endpoints are used by default. Per-match
shot/roster endpoints are available but cost one request per match, so callers
opt into them explicitly (see ``IngestionService(..., with_shots=True)``).
"""

from __future__ import annotations

from typing import Any, Optional

from .base import BaseCollector

# Six leagues exposed by Understat (code -> human label is resolved elsewhere).
UNDERSTAT_LEAGUES = ("EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1", "RFPL")


class UnderstatCollector(BaseCollector):
    """Fetch raw JSON from Understat and persist it under ``data/raw``."""

    @property
    def source_name(self) -> str:
        return "understat"

    # -- client lifecycle ---------------------------------------------------
    def _client(self):
        """Lazily import and instantiate the Understat client.

        Imported lazily so the rest of the project (schema, analysis, tests)
        works even when ``understatapi`` / network access is unavailable.
        """
        try:
            from understatapi import UnderstatClient
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "The 'understatapi' package is required for live collection. "
                "Install it with: pip install understatapi"
            ) from exc
        return UnderstatClient()

    # -- league-level endpoints (cheap: one request each) ------------------
    def fetch_league_matches(self, league: str, season: str) -> list[dict[str, Any]]:
        def _fetch() -> Any:
            with self._client() as client:
                return client.league(league=league).get_match_data(season=str(season))

        return self._fetch_with_cache("league_matches", f"{league}_{season}", _fetch)

    def fetch_league_teams(self, league: str, season: str) -> dict[str, Any]:
        def _fetch() -> Any:
            with self._client() as client:
                return client.league(league=league).get_team_data(season=str(season))

        return self._fetch_with_cache("league_teams", f"{league}_{season}", _fetch)

    def fetch_league_players(self, league: str, season: str) -> list[dict[str, Any]]:
        def _fetch() -> Any:
            with self._client() as client:
                return client.league(league=league).get_player_data(season=str(season))

        return self._fetch_with_cache("league_players", f"{league}_{season}", _fetch)

    # -- per-match endpoints (expensive: one request per match) ------------
    def fetch_match_shots(self, match_id: str) -> dict[str, Any]:
        def _fetch() -> Any:
            with self._client() as client:
                return client.match(match=str(match_id)).get_shot_data()

        return self._fetch_with_cache("match_shots", str(match_id), _fetch)

    def fetch_match_roster(self, match_id: str) -> dict[str, Any]:
        def _fetch() -> Any:
            with self._client() as client:
                return client.match(match=str(match_id)).get_roster_data()

        return self._fetch_with_cache("match_roster", str(match_id), _fetch)
