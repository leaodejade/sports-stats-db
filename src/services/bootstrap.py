"""One-shot bootstrap: ingest many leagues x seasons, then build features.

Automates the "fresh machine" data step so a single call populates the database
end to end. The collector is injected, so this is fully testable without network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.engine import Engine

from ..collectors.base import BaseCollector
from ..database import init_db, session_scope
from ..features import build_for_season
from ..models import Competition, Season
from ..utils.logging import get_logger
from .ingestion_service import IngestionService

logger = get_logger(__name__)


@dataclass
class BootstrapReport:
    ingested: list[tuple[str, str, str]] = field(default_factory=list)   # league, season, status
    failures: list[tuple[str, str, str]] = field(default_factory=list)   # league, season, error
    features_built: int = 0

    def as_dict(self) -> dict:
        return {
            "ingested": len(self.ingested),
            "failed": len(self.failures),
            "features_built": self.features_built,
            "failures": self.failures,
        }


def bootstrap(
    collector: BaseCollector,
    engine: Engine,
    leagues: list[str],
    seasons: list[str],
    with_features: bool = True,
    with_shots: bool = False,
) -> BootstrapReport:
    """Ingest every (league, season) pair, then optionally build features.

    Resilient: a failure on one pair is recorded and the rest continue.
    """
    init_db(engine)
    service = IngestionService(collector=collector, engine=engine)
    report = BootstrapReport()

    for league in leagues:
        for season in seasons:
            try:
                result = service.ingest_understat(league, str(season), with_shots=with_shots)
                report.ingested.append((league, str(season), result.status))
            except Exception as exc:  # noqa: BLE001 - record & continue
                logger.warning("Bootstrap failed for %s %s: %s", league, season, exc)
                report.failures.append((league, str(season), str(exc)[:200]))

    if with_features and report.ingested:
        with session_scope(engine) as session:
            for league, season, _status in report.ingested:
                comp = session.scalar(select(Competition).where(Competition.code == league))
                if comp is None:
                    continue
                season_obj = session.scalar(
                    select(Season).where(
                        Season.competition_id == comp.id,
                        Season.external_season == str(season),
                    )
                )
                if season_obj is None:
                    continue
                report.features_built += build_for_season(session, season_obj.id)

    logger.info("Bootstrap done: %s", report.as_dict())
    return report
