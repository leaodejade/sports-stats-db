"""Tests for the end-to-end ingestion service (with a fake collector)."""

from __future__ import annotations

from sqlalchemy import func, select

from src.database import get_session_factory
from src.models import (
    IngestionLog,
    Match,
    MatchPlayerStat,
    MatchTeamStat,
    PlayerSeasonStat,
    Shot,
    Standing,
    Team,
)
from src.services import IngestionService


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_core_ingestion_inserts_expected_rows(engine, ingestion_service):
    result = ingestion_service.ingest_understat("EPL", "2023")
    assert result.status == "success"

    session = get_session_factory(engine)()
    try:
        assert _count(session, Team) == 2
        assert _count(session, Match) == 2
        assert _count(session, Standing) == 2
        assert _count(session, PlayerSeasonStat) == 2
        assert _count(session, MatchTeamStat) == 4

        match = session.scalar(select(Match).where(Match.external_id == "1001"))
        assert match.home_goals == 1 and match.away_goals == 0
        assert match.is_result is True
    finally:
        session.close()


def test_match_team_stats_link_to_matches(engine, ingestion_service):
    ingestion_service.ingest_understat("EPL", "2023")
    session = get_session_factory(engine)()
    try:
        # Every team-match row should have been linked to a match by date.
        linked = session.scalars(
            select(MatchTeamStat).where(MatchTeamStat.match_id.is_not(None))
        ).all()
        assert len(linked) == 4
    finally:
        session.close()


def test_ingestion_is_idempotent(engine, ingestion_service):
    ingestion_service.ingest_understat("EPL", "2023")
    ingestion_service.ingest_understat("EPL", "2023")  # run twice

    session = get_session_factory(engine)()
    try:
        assert _count(session, Match) == 2  # no duplicates
        assert _count(session, Team) == 2
        assert _count(session, Standing) == 2
    finally:
        session.close()


def test_ingestion_log_written(engine, ingestion_service):
    ingestion_service.ingest_understat("EPL", "2023")
    session = get_session_factory(engine)()
    try:
        log = session.scalar(select(IngestionLog))
        assert log is not None
        assert log.status == "success"
        assert log.league == "EPL" and log.season == "2023"
        assert log.records_processed > 0
        assert log.duration_seconds is not None
    finally:
        session.close()


def test_deep_ingestion_adds_shots_and_player_stats(engine, fake_collector):
    service = IngestionService(collector=fake_collector, engine=engine)
    service.ingest_understat("EPL", "2023", with_shots=True)

    session = get_session_factory(engine)()
    try:
        assert _count(session, Shot) == 2
        assert _count(session, MatchPlayerStat) == 2

        goal = session.scalar(select(Shot).where(Shot.result == "Goal"))
        assert goal.is_home is True
        assert goal.match_id is not None
        assert goal.player_id is not None
    finally:
        session.close()
