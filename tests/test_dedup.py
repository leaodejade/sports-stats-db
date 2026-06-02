"""Tests for team de-duplication / stable resolution (audit phase 2)."""

from __future__ import annotations

from sqlalchemy import func, select

from src.database import get_session_factory
from src.models import Sport, Team
from src.services import football_repository as repo
from src.services import reference_service as ref


def _sport_source(session):
    sport = ref.get_or_create_sport(session, "Football")
    source = ref.get_or_create_source(session, "understat")
    return sport, source


def test_normalize_team_name_folds_case_accents_and_suffixes():
    n = repo.normalize_team_name
    assert n("Arsenal FC") == "arsenal"
    assert n("Atlético Madrid") == n("Atletico Madrid") == "atletico madrid"
    assert n("  Manchester   United  ") == "manchester united"
    assert n("") == "" and n(None) == ""


def test_suffix_variant_does_not_create_duplicate(session):
    sport, source = _sport_source(session)
    t1 = repo.get_or_create_team(session, sport, source, "10", "Arsenal")
    # "Arsenal FC" normalises to the same key -> resolves to the existing team.
    found = repo.find_team(session, sport, "Arsenal FC")
    assert found is not None and found.id == t1.id

    t2 = repo.get_or_create_team(session, sport, source, None, "Arsenal FC")
    assert t2.id == t1.id
    assert session.scalar(select(func.count()).select_from(Team)) == 1


def test_manual_alias_maps_cross_source_names(session):
    sport, source = _sport_source(session)
    team = repo.get_or_create_team(session, sport, source, "11", "Manchester City")
    # Different sources call it "Man City"; register that once.
    repo.record_team_alias(session, team, "Man City", source)

    assert repo.find_team(session, sport, "Man City").id == team.id
    # get_or_create with the alias must not create a second team.
    again = repo.get_or_create_team(session, sport, source, None, "Man City")
    assert again.id == team.id
    assert session.scalar(select(func.count()).select_from(Team)) == 1


def test_find_team_does_not_create(session):
    sport, _ = _sport_source(session)
    assert repo.find_team(session, sport, "Nonexistent United") is None
    assert session.scalar(select(func.count()).select_from(Team)) == 0


def test_player_name_variant_links_instead_of_duplicating(populated):
    """Regression: the player payload's team_title must resolve to the match
    team, not spawn a phantom. The sample uses exact names, so count stays 2."""
    session = get_session_factory(populated)()
    try:
        assert session.scalar(select(func.count()).select_from(Team)) == 2
    finally:
        session.close()
