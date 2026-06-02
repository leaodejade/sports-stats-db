"""Orchestrates a full Understat league+season ingestion.

Pipeline per run:
  collector (raw JSON)  ->  transformer (DTOs)  ->  repository (upserts)

The collector is injected, so tests drive the whole service with a fake
collector returning canned payloads — no network required. Every run is
recorded in ``ingestion_logs``, including failures.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..collectors import UnderstatCollector
from ..collectors.base import BaseCollector
from ..database.connection import session_scope
from ..models import IngestionLog, Match
from ..transformers import (
    transform_league_matches,
    transform_league_players,
    transform_league_teams,
    transform_match_shots,
    transform_roster,
)
from ..utils.logging import get_logger
from . import football_repository as repo
from . import reference_service as ref

logger = get_logger(__name__)


def _utcnow() -> datetime:
    """Naive UTC timestamp (stored as-is in the SQLite DateTime columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class IngestionResult:
    league: str
    season: str
    status: str
    counts: dict[str, int] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error_message: Optional[str] = None


class IngestionService:
    """Coordinates collection, transformation and persistence."""

    def __init__(
        self,
        collector: Optional[BaseCollector] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        self.collector = collector or UnderstatCollector()
        self.engine = engine

    # -- public API ---------------------------------------------------------
    def ingest_understat(
        self, league: str, season: str, with_shots: bool = False
    ) -> IngestionResult:
        season = str(season)
        started = _utcnow()
        counts: dict[str, int] = defaultdict(int)
        status = "success"
        error_message: Optional[str] = None

        try:
            with session_scope(self.engine) as session:
                self._ingest_core(session, league, season, counts)
                if with_shots:
                    self._ingest_deep(session, league, season, counts)
        except Exception as exc:  # noqa: BLE001 - logged & recorded, then re-raised
            status = "failed"
            error_message = str(exc)[:500]
            logger.exception("Ingestion failed for %s %s", league, season)
            raise
        finally:
            duration = (_utcnow() - started).total_seconds()
            self._write_log(
                league, season, status, dict(counts), started, duration, error_message
            )

        logger.info(
            "Ingested %s %s: %s",
            league,
            season,
            ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        )
        return IngestionResult(
            league=league,
            season=season,
            status=status,
            counts=dict(counts),
            duration_seconds=duration,
        )

    # -- core (cheap) ingestion --------------------------------------------
    def _ingest_core(
        self, session: Session, league: str, season: str, counts: dict[str, int]
    ) -> None:
        sport = ref.get_or_create_sport(session, "Football")
        source = ref.get_or_create_source(session, self.collector.source_name)
        competition = ref.get_or_create_competition(session, sport, source, league)
        season_obj = ref.get_or_create_season(session, competition, season)

        # 1) Matches (also creates the teams).
        raw_matches = self.collector.fetch_league_matches(league, season)
        for dto in transform_league_matches(raw_matches):
            home = repo.get_or_create_team(
                session, sport, source, dto.home_external_id, dto.home_name
            )
            away = repo.get_or_create_team(
                session, sport, source, dto.away_external_id, dto.away_name
            )
            repo.upsert_match(session, competition, season_obj, source, dto, home, away)
            counts["matches"] += 1
        session.flush()

        # 2) Team season standings + per-match team stats.
        raw_teams = self.collector.fetch_league_teams(league, season)
        standings, team_matches = transform_league_teams(raw_teams)

        standings.sort(
            key=lambda s: (s.points, s.goals_for - s.goals_against, s.goals_for),
            reverse=True,
        )
        for position, sdto in enumerate(standings, start=1):
            team = repo.get_or_create_team(
                session, sport, source, sdto.team_external_id, sdto.team_name
            )
            repo.upsert_standing(session, competition, season_obj, team, sdto, position)
            counts["standings"] += 1
        session.flush()

        match_lookup = repo.build_match_lookup(session, season_obj)
        for tdto in team_matches:
            team = repo.get_or_create_team(
                session, sport, source, tdto.team_external_id, tdto.team_name
            )
            match_id = None
            if tdto.match_date is not None:
                match_id = match_lookup.get((team.id, tdto.match_date.date()))
            repo.upsert_match_team_stat(session, season_obj, team, tdto, match_id)
            counts["match_team_stats"] += 1

        # 3) Player season aggregates.
        raw_players = self.collector.fetch_league_players(league, season)
        for pdto in transform_league_players(raw_players):
            player = repo.get_or_create_player(
                session, sport, source, pdto.external_id, pdto.name, pdto.position
            )
            team = None
            if pdto.team_title:
                first_team = pdto.team_title.split(",")[0].strip()
                team = repo.get_or_create_team(session, sport, source, None, first_team)
            repo.upsert_player_season(
                session, competition, season_obj, player, team, pdto
            )
            counts["players"] += 1

    # -- deep (expensive) ingestion: shots + rosters -----------------------
    def _ingest_deep(
        self, session: Session, league: str, season: str, counts: dict[str, int]
    ) -> None:
        sport = ref.get_or_create_sport(session, "Football")
        source = ref.get_or_create_source(session, self.collector.source_name)
        competition = ref.get_or_create_competition(session, sport, source, league)
        season_obj = ref.get_or_create_season(session, competition, season)

        matches = session.scalars(
            select(Match).where(
                Match.season_id == season_obj.id,
                Match.is_result.is_(True),
                Match.external_id.is_not(None),
            )
        ).all()

        logger.info("Deep ingestion for %d matches (%s %s)", len(matches), league, season)
        for match in matches:
            try:
                self._ingest_match_shots(session, source, sport, match, counts)
                self._ingest_match_roster(session, source, sport, match, counts)
                session.commit()
            except Exception as exc:  # noqa: BLE001 - per-match resilience
                session.rollback()
                counts["deep_errors"] += 1
                logger.warning(
                    "Deep ingest failed for match %s: %s", match.external_id, exc
                )

    def _ingest_match_shots(
        self, session: Session, source, sport, match: Match, counts: dict[str, int]
    ) -> None:
        raw = self.collector.fetch_match_shots(match.external_id)
        for dto in transform_match_shots(raw):
            player = None
            if dto.player_external_id:
                player = repo.get_or_create_player(
                    session, sport, source, dto.player_external_id, dto.player_name
                )
            team_id = None
            if dto.is_home is not None:
                team_id = match.home_team_id if dto.is_home else match.away_team_id
            repo.upsert_shot(
                session,
                source,
                dto,
                match.id,
                player.id if player else None,
                team_id,
            )
            counts["shots"] += 1

    def _ingest_match_roster(
        self, session: Session, source, sport, match: Match, counts: dict[str, int]
    ) -> None:
        raw = self.collector.fetch_match_roster(match.external_id)
        for dto in transform_roster(raw):
            if not dto.player_external_id:
                continue
            player = repo.get_or_create_player(
                session, sport, source, dto.player_external_id, dto.player_name
            )
            team_id = None
            if dto.is_home is not None:
                team_id = match.home_team_id if dto.is_home else match.away_team_id
            repo.upsert_match_player_stat(session, match.id, player, team_id, dto)
            counts["match_player_stats"] += 1

    # -- logging ------------------------------------------------------------
    def _write_log(
        self,
        league: str,
        season: str,
        status: str,
        counts: dict[str, int],
        started: datetime,
        duration: float,
        error_message: Optional[str],
    ) -> None:
        try:
            with session_scope(self.engine) as session:
                source = ref.get_or_create_source(session, self.collector.source_name)
                session.add(
                    IngestionLog(
                        source_id=source.id,
                        source_name=self.collector.source_name,
                        sport="Football",
                        entity="league_season",
                        league=league,
                        season=season,
                        status=status,
                        records_processed=sum(counts.values()),
                        started_at=started,
                        finished_at=_utcnow(),
                        duration_seconds=duration,
                        error_message=error_message,
                        raw_path=str(self.collector.raw_dir),
                    )
                )
        except Exception:  # noqa: BLE001 - logging must never mask the real error
            logger.exception("Failed to write ingestion log for %s %s", league, season)
