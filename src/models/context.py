"""Structured pre-match context and fundamentals.

Captures information a model may use as features or a human may read before a
match: refereeing/weather/importance (one row per match) and structured notes
for probable/confirmed line-ups, injuries and suspensions (never free text).

No active collector populates these yet — they exist so an external pipeline can
write them through a typed schema rather than dumping unstructured strings.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database.base import Base, TimestampMixin


class MatchContext(TimestampMixin, Base):
    """One-to-one contextual data for a match (referee, weather, importance...)."""

    __tablename__ = "match_context"
    __table_args__ = (
        UniqueConstraint("match_id", name="uq_match_context_match"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    referee: Mapped[Optional[str]] = mapped_column(String(120))
    attendance: Mapped[Optional[int]] = mapped_column(Integer)
    # e.g. "title_race" | "relegation" | "european_spot" | "dead_rubber"
    importance: Mapped[Optional[str]] = mapped_column(String(40))
    weather: Mapped[Optional[dict]] = mapped_column(JSON)  # {temp_c, condition, wind_kph}
    travel_km_home: Mapped[Optional[float]] = mapped_column(Float)
    travel_km_away: Mapped[Optional[float]] = mapped_column(Float)


class FundamentalNote(TimestampMixin, Base):
    """Structured fundamentals: probable/confirmed line-ups, injuries, suspensions.

    ``payload`` carries the structured detail (e.g. a list of player ids/names),
    so consumers parse JSON rather than scraping prose.
    """

    __tablename__ = "fundamental_notes"
    __table_args__ = (
        UniqueConstraint("match_id", "team_id", "kind", name="uq_fundamental_note"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[Optional[int]] = mapped_column(ForeignKey("matches.id"), index=True)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"), index=True)
    # "lineup_probable" | "lineup_confirmed" | "injury" | "suspension" | "news"
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    source_quality: Mapped[Optional[str]] = mapped_column(String(20))  # high|medium|low
    as_of: Mapped[Optional[datetime]] = mapped_column(DateTime)
