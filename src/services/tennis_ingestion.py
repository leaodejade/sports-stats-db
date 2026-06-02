"""Coordinates tennis data collection, transformation and persistence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..collectors.tennis_sackmann_collector import TennisSackmannCollector
from ..database.connection import session_scope
from ..models import IngestionLog
from ..transformers.tennis_transformer import (
    extract_tournaments,
    transform_tennis_matches,
    transform_tennis_players,
    transform_tennis_rankings,
)
from ..utils.logging import get_logger
from . import reference_service as ref
from . import tennis_repository as repo

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class TennisIngestionResult:
    tour: str
    season: str
    status: str
    counts: dict[str, int] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error_message: Optional[str] = None


class TennisIngestionService:
    def __init__(
        self,
        collector: Optional[TennisSackmannCollector] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        self.collector = collector or TennisSackmannCollector()
        self.engine = engine

    def ingest_tennis(self, tour: str, season: str) -> TennisIngestionResult:
        started = _utcnow()
        counts: dict[str, int] = defaultdict(int)
        status = "success"
        error_message: Optional[str] = None

        try:
            with session_scope(self.engine) as session:
                self._ingest_core(session, tour, season, counts)
        except Exception as exc:
            status = "failed"
            error_message = str(exc)[:500]
            logger.exception("Tennis ingestion failed for %s %s", tour, season)
            raise
        finally:
            duration = (_utcnow() - started).total_seconds()
            self._write_log(
                tour, season, status, dict(counts), started, duration, error_message
            )

        return TennisIngestionResult(
            tour=tour,
            season=season,
            status=status,
            counts=dict(counts),
            duration_seconds=duration,
        )

    def _ingest_core(
        self, session: Session, tour: str, season: str, counts: dict[str, int]
    ) -> None:
        sport = ref.get_or_create_sport(session, "Tennis")
        source = ref.get_or_create_source(session, self.collector.source_name)

        # Players
        raw_players = self.collector.fetch_players(tour)
        player_dtos = transform_tennis_players(raw_players)
        player_cache = {}
        for dto in player_dtos:
            p = repo.upsert_tennis_player(session, source, dto)
            player_cache[dto.external_id] = p
            counts["players"] += 1
        session.flush()

        # Matches & Tournaments
        raw_matches = self.collector.fetch_matches(tour, season)
        tournament_dtos = extract_tournaments(raw_matches)
        tournament_cache = {}
        for dto in tournament_dtos:
            t = repo.upsert_tennis_tournament(session, source, dto)
            tournament_cache[dto.external_id] = t
            counts["tournaments"] += 1
        session.flush()

        match_dtos = transform_tennis_matches(raw_matches)
        for dto in match_dtos:
            winner = player_cache.get(dto.winner_external_id)
            loser = player_cache.get(dto.loser_external_id)
            tourney = tournament_cache.get(dto.tournament_external_id)

            if winner and loser and tourney:
                repo.upsert_tennis_match(
                    session,
                    source,
                    dto,
                    tourney.id,
                    winner.id,
                    loser.id,
                )
                counts["matches"] += 1

        # We skip rankings for now unless requested to keep ingestion fast,
        # but the structure is in place.

    def _write_log(
        self,
        tour: str,
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
                        sport="Tennis",
                        entity="tour_season",
                        league=tour,
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
        except Exception:
            logger.exception("Failed to write ingestion log for %s %s", tour, season)
