"""Tests for tennis collector, transformer, and ingestion service."""

import pytest
from datetime import datetime, timezone
from src.collectors.tennis_sackmann_collector import TennisSackmannCollector
from src.transformers.tennis_transformer import (
    transform_tennis_matches, transform_tennis_players, extract_tournaments
)
from src.services.tennis_ingestion import TennisIngestionService
from src.database.connection import session_scope
from src.models.tennis import TennisPlayer, TennisMatch, TennisTournament


# --- FAKE DATA ---

SAMPLE_PLAYERS = [
    {
        "player_id": "104925", "name_first": "Novak", "name_last": "Djokovic",
        "hand": "R", "dob": "19870522", "ioc": "SRB", "height": "188"
    },
    {
        "player_id": "100644", "name_first": "Alexander", "name_last": "Zverev",
        "hand": "R", "dob": "19970420", "ioc": "GER", "height": "198"
    }
]

SAMPLE_MATCHES = [
    {
        "tourney_id": "2023-M020", "tourney_name": "Brisbane", "surface": "Hard",
        "tourney_date": "20230102", "match_num": "300", "winner_id": "104925",
        "loser_id": "100644", "score": "6-3 6-4", "best_of": "3", "round": "F",
        "minutes": "90", "w_ace": "5", "w_df": "1", "w_svpt": "50", "w_1stIn": "35",
        "w_1stWon": "30", "w_2ndWon": "10", "w_bpSaved": "2", "w_bpFaced": "2",
        "l_ace": "8", "l_df": "3", "l_svpt": "60", "l_1stIn": "30",
        "l_1stWon": "20", "l_2ndWon": "15", "l_bpSaved": "5", "l_bpFaced": "8",
        "tourney_level": "A"
    }
]

class FakeTennisCollector(TennisSackmannCollector):
    def fetch_players(self, tour: str):
        return SAMPLE_PLAYERS

    def fetch_matches(self, tour: str, season: str):
        return SAMPLE_MATCHES


# --- TESTS ---

def test_transform_tennis_players():
    dtos = transform_tennis_players(SAMPLE_PLAYERS)
    assert len(dtos) == 2
    assert dtos[0].name == "Novak Djokovic"
    assert dtos[0].birth_date == datetime(1987, 5, 22, tzinfo=timezone.utc)
    assert dtos[0].height_cm == 188.0

def test_extract_tournaments():
    dtos = extract_tournaments(SAMPLE_MATCHES)
    assert len(dtos) == 1
    assert dtos[0].name == "Brisbane"
    assert dtos[0].surface == "Hard"

def test_transform_tennis_matches():
    dtos = transform_tennis_matches(SAMPLE_MATCHES)
    assert len(dtos) == 1
    match = dtos[0]
    assert match.external_id == "2023-M020_300"
    assert match.score == "6-3 6-4"
    assert match.winner_stats.aces == 5
    assert match.loser_stats.break_points_faced == 8


@pytest.fixture
def fake_tennis_collector():
    return FakeTennisCollector()


def test_tennis_ingestion_idempotency(engine, fake_tennis_collector):
    service = TennisIngestionService(collector=fake_tennis_collector, engine=engine)

    # First ingestion
    result = service.ingest_tennis(tour="ATP", season="2023")
    assert result.status == "success"
    assert result.counts["players"] == 2
    assert result.counts["tournaments"] == 1
    assert result.counts["matches"] == 1

    # Second ingestion should be idempotent
    result2 = service.ingest_tennis(tour="ATP", season="2023")
    assert result2.status == "success"

    # Verify no duplicates in DB
    with session_scope(engine) as session:
        players_count = session.query(TennisPlayer).count()
        assert players_count == 2
        matches_count = session.query(TennisMatch).count()
        assert matches_count == 1
        tournaments_count = session.query(TennisTournament).count()
        assert tournaments_count == 1
