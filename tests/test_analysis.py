"""Tests for aggregated analytical queries."""

from __future__ import annotations

from src.analysis import football as fb
from src.database import get_session_factory


def _session(engine):
    return get_session_factory(engine)()


def test_xg_table_orders_and_populates(populated):
    session = _session(populated)
    try:
        df = fb.xg_table(session, league="EPL", season="2023")
        assert len(df) == 2
        assert set(df["team"]) == {"Arsenal", "Manchester City"}
        # Position 1 must be the higher goal-difference side (Man City).
        assert df.iloc[0]["team"] == "Manchester City"
    finally:
        session.close()


def test_team_xg_ranking(populated):
    session = _session(populated)
    try:
        df = fb.team_xg_ranking(session, league="EPL", season="2023")
        assert df.iloc[0]["team"] == "Manchester City"  # highest xG (4.3)
        assert df.iloc[0]["rank"] == 1
    finally:
        session.close()


def test_top_players_by_xg(populated):
    session = _session(populated)
    try:
        df = fb.top_players_by_xg(session, league="EPL", season="2023")
        assert df.iloc[0]["player"] == "Erling Haaland"  # xG 2.4
    finally:
        session.close()


def test_real_vs_expected(populated):
    session = _session(populated)
    try:
        df = fb.real_vs_expected(session, league="EPL", season="2023")
        assert "pts_diff" in df.columns
        assert len(df) == 2
        # Both teams scored 3 points vs differing xPTS -> column is computed.
        assert df["pts_diff"].notna().all()
    finally:
        session.close()


def test_recent_form(populated):
    session = _session(populated)
    try:
        df = fb.recent_form(session, team="Arsenal", season="2023", n=5)
        assert len(df) == 2  # only two matches ingested
        # Most recent first: the March match (a loss) leads.
        assert df.iloc[0]["result"] == "l"
    finally:
        session.close()


def test_unknown_season_returns_empty(populated):
    session = _session(populated)
    try:
        df = fb.xg_table(session, league="EPL", season="1999")
        assert df.empty
    finally:
        session.close()
