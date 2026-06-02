"""Tests for connection, table creation and reference seeding."""

from __future__ import annotations

from sqlalchemy import inspect, select, text

from src.models import Base, DataSource, Sport, TennisSurface

EXPECTED_TABLES = {
    "sports", "countries", "competitions", "seasons", "teams", "players",
    "matches", "match_team_stats", "match_player_stats", "shots", "standings",
    "player_season_stats", "data_sources", "ingestion_logs",
    "tennis_players", "tennis_tournaments", "tennis_matches",
    "tennis_match_stats", "tennis_rankings", "tennis_surfaces",
}


def test_engine_connects(engine):
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_all_tables_created(engine):
    tables = set(inspect(engine).get_table_names())
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Missing tables: {missing}"


def test_metadata_matches_models():
    # Every expected table is declared on the shared metadata.
    assert EXPECTED_TABLES.issubset(set(Base.metadata.tables))


def test_reference_data_seeded(session):
    sports = session.scalars(select(Sport.name)).all()
    assert "Football" in sports and "Tennis" in sports

    assert session.scalar(select(DataSource).where(DataSource.name == "understat"))

    surfaces = session.scalars(select(TennisSurface.name)).all()
    assert {"Hard", "Clay", "Grass", "Carpet"}.issubset(set(surfaces))


def test_seed_is_idempotent(engine, session):
    from src.database import seed_reference_data

    seed_reference_data(engine)  # run again
    football_count = len(
        session.scalars(select(Sport).where(Sport.name == "Football")).all()
    )
    assert football_count == 1
