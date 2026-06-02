"""Tennis relational schema (future expansion).

These tables are created alongside the football schema so the database is
ready for a tennis collector, but no collector populates them yet. They share
``countries`` / ``data_sources`` with the football models.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.base import Base, TimestampMixin


class TennisSurface(TimestampMixin, Base):
    __tablename__ = "tennis_surfaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)


class TennisPlayer(TimestampMixin, Base):
    __tablename__ = "tennis_players"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))
    country_id: Mapped[Optional[int]] = mapped_column(ForeignKey("countries.id"))
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    hand: Mapped[Optional[str]] = mapped_column(String(10))  # L / R
    birth_date: Mapped[Optional[date]] = mapped_column(Date)


class TennisTournament(TimestampMixin, Base):
    __tablename__ = "tennis_tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))
    surface_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tennis_surfaces.id"))
    country_id: Mapped[Optional[int]] = mapped_column(ForeignKey("countries.id"))
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50))  # GS, Masters, ATP250
    season_year: Mapped[Optional[int]] = mapped_column(Integer)
    start_date: Mapped[Optional[date]] = mapped_column(Date)


class TennisMatch(TimestampMixin, Base):
    __tablename__ = "tennis_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tennis_tournaments.id"), nullable=False
    )
    surface_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tennis_surfaces.id"))
    player1_id: Mapped[int] = mapped_column(
        ForeignKey("tennis_players.id"), nullable=False
    )
    player2_id: Mapped[int] = mapped_column(
        ForeignKey("tennis_players.id"), nullable=False
    )
    winner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tennis_players.id"))
    external_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    round: Mapped[Optional[str]] = mapped_column(String(30))
    best_of: Mapped[Optional[int]] = mapped_column(Integer)
    score: Mapped[Optional[str]] = mapped_column(String(60))
    match_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    player1: Mapped["TennisPlayer"] = relationship(foreign_keys=[player1_id])
    player2: Mapped["TennisPlayer"] = relationship(foreign_keys=[player2_id])


class TennisMatchStat(TimestampMixin, Base):
    """Serve / return splits for one player in one match."""

    __tablename__ = "tennis_match_stats"
    __table_args__ = (
        UniqueConstraint("match_id", "player_id", name="uq_tennis_stat_match_player"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("tennis_matches.id"), nullable=False
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("tennis_players.id"), nullable=False
    )

    aces: Mapped[Optional[int]] = mapped_column(Integer)
    double_faults: Mapped[Optional[int]] = mapped_column(Integer)
    first_serve_in: Mapped[Optional[int]] = mapped_column(Integer)
    first_serve_pct: Mapped[Optional[float]] = mapped_column(Float)
    first_serve_points_won: Mapped[Optional[int]] = mapped_column(Integer)
    serve_points: Mapped[Optional[int]] = mapped_column(Integer)
    second_serve_points_won: Mapped[Optional[int]] = mapped_column(Integer)
    service_games_won: Mapped[Optional[int]] = mapped_column(Integer)
    break_points_saved: Mapped[Optional[int]] = mapped_column(Integer)
    break_points_faced: Mapped[Optional[int]] = mapped_column(Integer)
    return_points_won: Mapped[Optional[int]] = mapped_column(Integer)
    total_points_won: Mapped[Optional[int]] = mapped_column(Integer)


class TennisRanking(TimestampMixin, Base):
    __tablename__ = "tennis_rankings"
    __table_args__ = (
        UniqueConstraint(
            "player_id", "ranking_date", "tour", name="uq_tennis_rank_player_date_tour"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("tennis_players.id"), nullable=False
    )
    ranking_date: Mapped[date] = mapped_column(Date, nullable=False)
    tour: Mapped[Optional[str]] = mapped_column(String(10))  # ATP / WTA
    rank: Mapped[Optional[int]] = mapped_column(Integer)
    points: Mapped[Optional[int]] = mapped_column(Integer)
