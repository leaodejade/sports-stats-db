"""Tests for structured pre-match context & fundamentals (audit phase 4)."""

from __future__ import annotations

from sqlalchemy import func, select

from src.models import FundamentalNote, MatchContext, MatchTeamStat
from src.services import betting_repository as br
from src.services import football_repository as repo


def _match(session):
    return br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")


def test_match_context_upsert_is_idempotent(session):
    mid = _match(session)
    repo.upsert_match_context(session, mid, referee="M. Oliver",
                              weather={"temp_c": 12, "condition": "rain"},
                              importance="title_race")
    repo.upsert_match_context(session, mid, attendance=60000)  # partial update

    assert session.scalar(select(func.count()).select_from(MatchContext)) == 1
    ctx = session.scalar(select(MatchContext).where(MatchContext.match_id == mid))
    assert ctx.referee == "M. Oliver"
    assert ctx.weather["condition"] == "rain"
    assert ctx.attendance == 60000
    assert ctx.importance == "title_race"


def test_fundamental_note_is_structured_and_idempotent(session):
    mid = _match(session)
    repo.upsert_fundamental_note(
        session, kind="lineup_confirmed", match_id=mid,
        payload={"starting_xi": ["Saka", "Odegaard", "Saliba"]},
        source_url="https://example.com/lineup", source_quality="high")
    # Same (match, team, kind) -> update, not duplicate.
    repo.upsert_fundamental_note(
        session, kind="lineup_confirmed", match_id=mid,
        payload={"starting_xi": ["Saka", "Rice"]}, source_quality="medium")

    notes = session.scalars(select(FundamentalNote)).all()
    assert len(notes) == 1
    assert notes[0].payload["starting_xi"] == ["Saka", "Rice"]
    assert notes[0].source_quality == "medium"
    assert isinstance(notes[0].payload, dict)  # structured, not free text


def test_distinct_note_kinds_coexist(session):
    mid = _match(session)
    repo.upsert_fundamental_note(session, kind="injury", match_id=mid,
                                 payload={"player": "Timber", "status": "out"})
    repo.upsert_fundamental_note(session, kind="suspension", match_id=mid,
                                 payload={"player": "Rice", "games": 1})
    assert session.scalar(select(func.count()).select_from(FundamentalNote)) == 2


def test_team_match_stat_has_context_columns(session):
    """The new corners/cards/possession/SoT columns exist and persist."""
    from src.models import Match, Season, Team

    mid = _match(session)  # creates EPL 2023 season + teams
    match = session.get(Match, mid)
    season = session.get(Season, match.season_id)
    row = MatchTeamStat(season_id=season.id, team_id=match.home_team_id,
                        corners=7, shots_on_target=5, yellow_cards=2,
                        possession=58.5)
    session.add(row)
    session.flush()
    fetched = session.get(MatchTeamStat, row.id)
    assert fetched.corners == 7
    assert fetched.shots_on_target == 5
    assert fetched.possession == 58.5
