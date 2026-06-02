"""Tests for Understat -> DTO transformation logic."""

from __future__ import annotations

from datetime import datetime

from src.transformers import (
    transform_league_matches,
    transform_league_players,
    transform_league_teams,
    transform_match_shots,
    transform_roster,
)
from src.transformers.base import normalize_ppda, to_bool_home, to_float, to_int


def test_type_coercion_is_defensive():
    assert to_int("34") == 34
    assert to_int("3.0") == 3
    assert to_int("") is None
    assert to_int(None) is None
    assert to_float("2.4") == 2.4
    assert to_float("nan-ish") is None
    assert to_bool_home("h") is True
    assert to_bool_home("a") is False
    assert normalize_ppda({"att": 300, "def": 20}) == 15.0


def test_transform_league_matches(understat_raw):
    dtos = transform_league_matches(understat_raw["league_matches"])
    assert len(dtos) == 2

    first = dtos[0]
    assert first.external_id == "1001"
    assert first.home_name == "Arsenal"
    assert first.away_name == "Manchester City"
    assert first.home_goals == 1 and first.away_goals == 0
    assert first.home_xg == 1.2 and first.away_xg == 1.8
    assert first.is_result is True
    assert first.match_datetime == datetime(2023, 10, 8, 16, 30, 0)


def test_transform_league_teams_aggregates(understat_raw):
    standings, team_matches = transform_league_teams(understat_raw["league_teams"])

    assert len(team_matches) == 4  # 2 teams x 2 matches
    by_name = {s.team_name: s for s in standings}

    arsenal = by_name["Arsenal"]
    assert arsenal.matches_played == 2
    assert arsenal.points == 3
    assert arsenal.goals_for == 2 and arsenal.goals_against == 3
    assert round(arsenal.xg, 1) == 2.1  # 1.2 + 0.9
    assert arsenal.form == "WL"

    city = by_name["Manchester City"]
    assert round(city.xg, 1) == 4.3  # 1.8 + 2.5


def test_transform_league_players(understat_raw):
    dtos = transform_league_players(understat_raw["league_players"])
    haaland = next(p for p in dtos if p.name == "Erling Haaland")
    assert haaland.goals == 3
    assert haaland.xg == 2.4
    assert haaland.external_id == "502"


def test_transform_shots_and_roster(understat_raw):
    shots = transform_match_shots(understat_raw["shots"]["1001"])
    assert len(shots) == 2
    goal = next(s for s in shots if s.result == "Goal")
    assert goal.is_home is True
    assert goal.player_external_id == "501"
    assert goal.xg == 0.45

    roster = transform_roster(understat_raw["rosters"]["1001"])
    assert len(roster) == 2
    saka = next(r for r in roster if r.player_external_id == "501")
    assert saka.minutes == 90 and saka.is_home is True
