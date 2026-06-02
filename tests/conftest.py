"""Shared pytest fixtures: isolated SQLite DB, sample payloads, fake collector."""

from __future__ import annotations

from typing import Any

import pytest

from src.database import create_db_engine, get_session_factory, init_db
from src.services import IngestionService


# ---------------------------------------------------------------------------
# Sample raw Understat payloads (2 teams, 2 matches, 2 players)
# ---------------------------------------------------------------------------
def sample_understat_raw() -> dict[str, Any]:
    league_matches = [
        {
            "id": "1001", "isResult": True,
            "h": {"id": "1", "title": "Arsenal", "short_title": "ARS"},
            "a": {"id": "2", "title": "Manchester City", "short_title": "MCI"},
            "goals": {"h": "1", "a": "0"}, "xG": {"h": "1.2", "a": "1.8"},
            "datetime": "2023-10-08 16:30:00",
            "forecast": {"w": "0.3", "d": "0.3", "l": "0.4"},
        },
        {
            "id": "1002", "isResult": True,
            "h": {"id": "2", "title": "Manchester City", "short_title": "MCI"},
            "a": {"id": "1", "title": "Arsenal", "short_title": "ARS"},
            "goals": {"h": "3", "a": "1"}, "xG": {"h": "2.5", "a": "0.9"},
            "datetime": "2024-03-31 15:30:00",
            "forecast": {"w": "0.6", "d": "0.2", "l": "0.2"},
        },
    ]

    league_teams = {
        "1": {
            "id": "1", "title": "Arsenal",
            "history": [
                {"h_a": "h", "xG": "1.2", "xGA": "1.8", "npxG": "1.1",
                 "ppda": {"att": 300, "def": 20}, "deep": "5", "deep_allowed": "7",
                 "scored": "1", "missed": "0", "xpts": "1.4", "result": "w",
                 "date": "2023-10-08 16:30:00", "wins": "1", "draws": "0",
                 "loses": "0", "pts": "3", "npxGD": "-0.7"},
                {"h_a": "a", "xG": "0.9", "xGA": "2.5", "npxG": "0.9",
                 "ppda": {"att": 250, "def": 25}, "deep": "3", "deep_allowed": "9",
                 "scored": "1", "missed": "3", "xpts": "0.6", "result": "l",
                 "date": "2024-03-31 15:30:00", "wins": "0", "draws": "0",
                 "loses": "1", "pts": "0", "npxGD": "-1.6"},
            ],
        },
        "2": {
            "id": "2", "title": "Manchester City",
            "history": [
                {"h_a": "a", "xG": "1.8", "xGA": "1.2", "npxG": "1.7",
                 "ppda": {"att": 200, "def": 30}, "deep": "7", "deep_allowed": "5",
                 "scored": "0", "missed": "1", "xpts": "1.6", "result": "l",
                 "date": "2023-10-08 16:30:00", "wins": "0", "draws": "0",
                 "loses": "1", "pts": "0", "npxGD": "0.5"},
                {"h_a": "h", "xG": "2.5", "xGA": "0.9", "npxG": "2.4",
                 "ppda": {"att": 180, "def": 28}, "deep": "9", "deep_allowed": "3",
                 "scored": "3", "missed": "1", "xpts": "2.4", "result": "w",
                 "date": "2024-03-31 15:30:00", "wins": "1", "draws": "0",
                 "loses": "0", "pts": "3", "npxGD": "1.5"},
            ],
        },
    }

    league_players = [
        {"id": "501", "player_name": "Bukayo Saka", "team_title": "Arsenal",
         "games": "2", "time": "180", "goals": "1", "xG": "0.8", "assists": "1",
         "xA": "0.6", "shots": "6", "key_passes": "4", "yellow_cards": "0",
         "red_cards": "0", "position": "F M S", "npg": "1", "npxG": "0.7",
         "xGChain": "1.5", "xGBuildup": "0.4"},
        {"id": "502", "player_name": "Erling Haaland", "team_title": "Manchester City",
         "games": "2", "time": "180", "goals": "3", "xG": "2.4", "assists": "0",
         "xA": "0.3", "shots": "9", "key_passes": "2", "yellow_cards": "1",
         "red_cards": "0", "position": "F S", "npg": "3", "npxG": "2.4",
         "xGChain": "2.8", "xGBuildup": "0.5"},
    ]

    shots = {
        "1001": {
            "h": [{"id": "9001", "minute": "23", "result": "Goal", "X": "0.9",
                   "Y": "0.5", "xG": "0.45", "player": "Bukayo Saka",
                   "player_id": "501", "situation": "OpenPlay", "shotType": "LeftFoot",
                   "match_id": "1001", "h_a": "h", "player_assisted": "Martin Odegaard",
                   "lastAction": "Pass"}],
            "a": [{"id": "9002", "minute": "61", "result": "SavedShot", "X": "0.85",
                   "Y": "0.45", "xG": "0.30", "player": "Erling Haaland",
                   "player_id": "502", "situation": "OpenPlay", "shotType": "RightFoot",
                   "match_id": "1001", "h_a": "a", "player_assisted": "Kevin De Bruyne",
                   "lastAction": "Pass"}],
        }
    }

    rosters = {
        "1001": {
            "h": {"501": {"id": "r1", "goals": "1", "own_goals": "0", "shots": "3",
                          "xG": "0.45", "time": "90", "player_id": "501", "team_id": "1",
                          "position": "FW", "player": "Bukayo Saka", "h_a": "h",
                          "yellow_card": "0", "red_card": "0", "key_passes": "2",
                          "assists": "0", "xA": "0.2", "xGChain": "0.9",
                          "xGBuildup": "0.1", "npg": "1", "npxG": "0.45"}},
            "a": {"502": {"id": "r2", "goals": "0", "own_goals": "0", "shots": "4",
                          "xG": "0.30", "time": "90", "player_id": "502", "team_id": "2",
                          "position": "FW", "player": "Erling Haaland", "h_a": "a",
                          "yellow_card": "1", "red_card": "0", "key_passes": "1",
                          "assists": "0", "xA": "0.1", "xGChain": "0.6",
                          "xGBuildup": "0.0", "npg": "0", "npxG": "0.30"}},
        }
    }

    return {
        "league_matches": league_matches,
        "league_teams": league_teams,
        "league_players": league_players,
        "shots": shots,
        "rosters": rosters,
    }


class FakeUnderstatCollector:
    """Stand-in for UnderstatCollector that serves canned payloads (no network)."""

    source_name = "understat"

    def __init__(self, data: dict[str, Any], raw_dir: str = "."):
        self._data = data
        self.raw_dir = raw_dir
        self.calls: list[tuple] = []

    def fetch_league_matches(self, league: str, season: str):
        self.calls.append(("matches", league, season))
        return self._data["league_matches"]

    def fetch_league_teams(self, league: str, season: str):
        self.calls.append(("teams", league, season))
        return self._data["league_teams"]

    def fetch_league_players(self, league: str, season: str):
        self.calls.append(("players", league, season))
        return self._data["league_players"]

    def fetch_match_shots(self, match_id: str):
        return self._data["shots"].get(str(match_id), {"h": [], "a": []})

    def fetch_match_roster(self, match_id: str):
        return self._data["rosters"].get(str(match_id), {"h": {}, "a": {}})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def engine(tmp_path):
    db_file = tmp_path / "test.db"
    eng = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    factory = get_session_factory(engine)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture()
def understat_raw():
    return sample_understat_raw()


@pytest.fixture()
def fake_collector(understat_raw, tmp_path):
    return FakeUnderstatCollector(understat_raw, raw_dir=str(tmp_path))


@pytest.fixture()
def ingestion_service(engine, fake_collector):
    return IngestionService(collector=fake_collector, engine=engine)


@pytest.fixture()
def populated(engine, ingestion_service):
    """Engine with one ingested league+season (core data only)."""
    ingestion_service.ingest_understat("EPL", "2023")
    return engine
