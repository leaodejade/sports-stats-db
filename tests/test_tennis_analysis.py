"""Tests for tennis analysis queries."""

import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database.connection import get_session_factory
from src.analysis import tennis as ta
from src.models import DataSource, Sport
from src.models.tennis import (
    TennisMatch, TennisMatchStat, TennisPlayer, TennisSurface, TennisTournament
)


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite database and seed it."""
    engine = create_engine("sqlite:///:memory:")
    from src.database import create_all, init_db
    init_db(engine)

    SessionLocal = get_session_factory(engine)
    session = SessionLocal()

    # Seeding test data
    source = session.query(DataSource).first()

    surface1 = session.query(TennisSurface).filter_by(name="Hard").first()
    surface2 = session.query(TennisSurface).filter_by(name="Clay").first()

    p1 = TennisPlayer(name="Novak Djokovic", source_id=source.id)
    p2 = TennisPlayer(name="Rafael Nadal", source_id=source.id)
    p3 = TennisPlayer(name="Roger Federer", source_id=source.id)
    session.add_all([p1, p2, p3])
    session.commit()

    t1 = TennisTournament(name="Australian Open", surface_id=surface1.id, source_id=source.id)
    t2 = TennisTournament(name="Roland Garros", surface_id=surface2.id, source_id=source.id)
    session.add_all([t1, t2])
    session.commit()

    m1 = TennisMatch(
        tournament_id=t1.id, player1_id=p1.id, player2_id=p2.id, winner_id=p1.id
    )
    m2 = TennisMatch(
        tournament_id=t2.id, player1_id=p1.id, player2_id=p2.id, winner_id=p2.id
    )
    m3 = TennisMatch(
        tournament_id=t2.id, player1_id=p2.id, player2_id=p3.id, winner_id=p2.id
    )
    session.add_all([m1, m2, m3])
    session.commit()

    s1 = TennisMatchStat(
        match_id=m1.id, player_id=p1.id, serve_points=100, first_serve_points_won=60, second_serve_points_won=20
    )
    s2 = TennisMatchStat(
        match_id=m2.id, player_id=p1.id, serve_points=120, first_serve_points_won=50, second_serve_points_won=25
    )
    s3 = TennisMatchStat(
        match_id=m1.id, player_id=p2.id, serve_points=90, first_serve_points_won=45, second_serve_points_won=15
    )
    session.add_all([s1, s2, s3])
    session.commit()

    yield session
    session.close()


def test_serve_points_won_ranking(db_session):
    df = ta.serve_points_won_ranking(db_session, min_serve_points=50)
    assert not df.empty
    assert len(df) == 2
    assert "serve_points_won_pct" in df.columns
    # p1 total won = 80 + 75 = 155. total attempted = 220. pct = 155/220 = 70.45
    # p2 total won = 60. total attempted = 90. pct = 66.67
    assert df.iloc[0]["player"] == "Novak Djokovic"
    assert df.iloc[0]["serve_points_won_pct"] == 70.45


def test_win_rate_by_surface(db_session):
    df = ta.win_rate_by_surface(db_session, "Novak Djokovic")
    assert not df.empty
    assert len(df) == 2
    hard = df[df["surface"] == "Hard"].iloc[0]
    clay = df[df["surface"] == "Clay"].iloc[0]
    assert hard["wins"] == 1
    assert clay["losses"] == 1
    assert hard["win_rate"] == 1.0
    assert clay["win_rate"] == 0.0


def test_head_to_head(db_session):
    df = ta.head_to_head(db_session, "Novak Djokovic", "Rafael Nadal")
    assert not df.empty
    assert df.iloc[0]["matches"] == 2
    assert df.iloc[0]["wins_a"] == 1
    assert df.iloc[0]["wins_b"] == 1


def test_head_to_head_empty(db_session):
    df = ta.head_to_head(db_session, "Novak Djokovic", "Unknown")
    assert df.empty
    assert list(df.columns) == ["player_a", "player_b", "matches", "wins_a", "wins_b"]
