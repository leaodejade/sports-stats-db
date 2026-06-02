"""Tests for data quality validation."""

import pytest
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database.connection import get_session_factory
from src.analysis import data_quality as dq
from src.models import DataSource, Sport, Competition, Season, Team, Match, MatchTeamStat, Shot


@pytest.fixture()
def bad_data_session():
    engine = create_engine("sqlite:///:memory:")
    from src.database import create_all, init_db
    init_db(engine)

    SessionLocal = get_session_factory(engine)
    session = SessionLocal()

    sport = session.query(Sport).first()
    source = session.query(DataSource).first()
    comp = Competition(sport_id=sport.id, source_id=source.id, name="Test League", code="test-league")
    session.add(comp)
    session.flush()

    season = Season(competition_id=comp.id, external_season="2023", label="2023", year_start=2023)
    session.add(season)
    session.flush()

    team1 = Team(sport_id=sport.id, source_id=source.id, name="Team A")
    team2 = Team(sport_id=sport.id, source_id=source.id, name="Team B")
    session.add_all([team1, team2])
    session.flush()

    # Match 1: Missing goals/xG despite is_result=True
    m1 = Match(
        competition_id=comp.id, season_id=season.id, source_id=source.id,
        home_team_id=team1.id, away_team_id=team2.id,
        match_datetime=datetime(2023, 1, 1), is_result=True,
        home_goals=None, away_goals=None, home_xg=1.0, away_xg=1.0
    )

    # Match 2: Valid match, but shot xG sums to 1.5, while team_stat xG is 2.0 (mismatch)
    # Also goals in team stat = 2, but shots say 1 goal (mismatch)
    m2 = Match(
        competition_id=comp.id, season_id=season.id, source_id=source.id,
        home_team_id=team1.id, away_team_id=team2.id,
        match_datetime=datetime(2023, 1, 2), is_result=True,
        home_goals=2, away_goals=0, home_xg=2.0, away_xg=0.0
    )
    session.add_all([m1, m2])
    session.flush()

    # MatchTeamStats
    mt1 = MatchTeamStat(
        season_id=season.id, team_id=team1.id, match_id=m2.id,
        match_date=datetime(2023, 1, 2),
        goals=2, xg=2.0
    )

    # Unlinked match stat
    mt2 = MatchTeamStat(
        season_id=season.id, team_id=team2.id, match_id=None,
        match_date=datetime(2023, 1, 3),
        goals=0, xg=0.0
    )
    session.add_all([mt1, mt2])
    session.flush()

    # Shots for Match 2
    # Sum xG = 1.0 + 0.5 = 1.5
    # Goals = 1
    s1 = Shot(
        source_id=source.id, match_id=m2.id, team_id=team1.id,
        xg=1.0, result="Goal"
    )
    s2 = Shot(
        source_id=source.id, match_id=m2.id, team_id=team1.id,
        xg=0.5, result="SavedShot"
    )
    session.add_all([s1, s2])
    session.commit()

    yield session
    session.close()

def test_validate_xg_sums(bad_data_session):
    df = dq.validate_xg_sums(bad_data_session)
    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["team_xg"] == 2.0
    assert df.iloc[0]["shot_xg_sum"] == 1.5

def test_validate_goals_vs_shots(bad_data_session):
    df = dq.validate_goals_vs_shots(bad_data_session)
    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["team_goals"] == 2
    assert df.iloc[0]["goals_from_shots"] == 1

def test_validate_match_has_score_and_xg(bad_data_session):
    df = dq.validate_match_has_score_and_xg(bad_data_session)
    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["home_goals"] is None

def test_validate_match_team_stats_linked(bad_data_session):
    df = dq.validate_match_team_stats_linked(bad_data_session)
    assert not df.empty
    assert len(df) == 1
    # Check that it converted correctly to Timestamp (pandas representation of datetime)
    assert df.iloc[0]["match_date"] == pd.Timestamp(2023, 1, 3)

def test_run_all_validations(bad_data_session):
    df = dq.run_all_validations(bad_data_session)
    assert not df.empty
    assert len(df) == 4
    types = df["type"].tolist()
    assert "xg_sum_mismatch" in types
    assert "goals_mismatch" in types
    assert "missing_score_xg" in types
    assert "unlinked_match_stat" in types
