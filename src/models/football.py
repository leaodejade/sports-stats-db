"""Football (soccer) relational schema.

Designed around what Understat exposes, but column names are source-agnostic so
other collectors (FBref, etc.) can populate the same tables later. External
identifiers and the originating data source are tracked on every core entity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.base import Base, TimestampMixin


# ---------------------------------------------------------------------------
# Reference / shared dimension tables
# ---------------------------------------------------------------------------
class Sport(TimestampMixin, Base):
    __tablename__ = "sports"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)


class Country(TimestampMixin, Base):
    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    iso_code: Mapped[Optional[str]] = mapped_column(String(3))


class DataSource(TimestampMixin, Base):
    """Where a row originated (understat, fbref, manual, ...)."""

    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    base_url: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(255))
    # Coarse confidence in this source: "high" | "medium" | "low".
    reliability: Mapped[Optional[str]] = mapped_column(String(20))


# ---------------------------------------------------------------------------
# Competition structure
# ---------------------------------------------------------------------------
class Competition(TimestampMixin, Base):
    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"), nullable=False)
    country_id: Mapped[Optional[int]] = mapped_column(ForeignKey("countries.id"))
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # External league code, e.g. Understat "EPL", "La_liga".
    code: Mapped[Optional[str]] = mapped_column(String(50), unique=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(50))

    sport: Mapped["Sport"] = relationship()
    country: Mapped[Optional["Country"]] = relationship()
    seasons: Mapped[list["Season"]] = relationship(back_populates="competition")


class Season(TimestampMixin, Base):
    __tablename__ = "seasons"
    __table_args__ = (
        UniqueConstraint("competition_id", "external_season", name="uq_season_comp_ext"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id"), nullable=False
    )
    # Understat encodes a season by its starting year, e.g. "2023" == 2023/24.
    external_season: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    year_start: Mapped[Optional[int]] = mapped_column(Integer)
    year_end: Mapped[Optional[int]] = mapped_column(Integer)

    competition: Mapped["Competition"] = relationship(back_populates="seasons")


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------
class Team(TimestampMixin, Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("sport_id", "external_id", name="uq_team_sport_ext"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"), nullable=False)
    country_id: Mapped[Optional[int]] = mapped_column(ForeignKey("countries.id"))
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)


class TeamAlias(TimestampMixin, Base):
    """Alternative names for a team, so different sources map to one entity.

    ``alias`` is stored normalised (lower-case, accent/punctuation-stripped).
    A given normalised alias maps to exactly one team per sport.
    """

    __tablename__ = "team_aliases"
    __table_args__ = (
        UniqueConstraint("sport_id", "alias", name="uq_team_alias"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))
    alias: Mapped[str] = mapped_column(String(120), nullable=False)


class Player(TimestampMixin, Base):
    __tablename__ = "players"
    __table_args__ = (
        UniqueConstraint("sport_id", "external_id", name="uq_player_sport_ext"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sport_id: Mapped[int] = mapped_column(ForeignKey("sports.id"), nullable=False)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    position: Mapped[Optional[str]] = mapped_column(String(50))


class Match(TimestampMixin, Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_match_source_ext"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id"), nullable=False
    )
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))
    external_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)

    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    match_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)

    home_goals: Mapped[Optional[int]] = mapped_column(Integer)
    away_goals: Mapped[Optional[int]] = mapped_column(Integer)
    home_xg: Mapped[Optional[float]] = mapped_column(Float)
    away_xg: Mapped[Optional[float]] = mapped_column(Float)

    # Understat win/draw/loss "forecast" (home perspective).
    # WARNING: for finished matches this is a POST-match retrodiction derived
    # from that match's own shot xG (corr ~0.997 with a Poisson model on the
    # same xG). It is NOT available pre-kickoff -- never use it as a pre-match
    # feature or in a betting backtest (it leaks the result). Store real
    # pre-match model output in the ``predictions`` table instead.
    forecast_w: Mapped[Optional[float]] = mapped_column(Float)
    forecast_d: Mapped[Optional[float]] = mapped_column(Float)
    forecast_l: Mapped[Optional[float]] = mapped_column(Float)

    is_result: Mapped[bool] = mapped_column(Boolean, default=False)

    home_team: Mapped["Team"] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped["Team"] = relationship(foreign_keys=[away_team_id])


# ---------------------------------------------------------------------------
# Per-match statistics
# ---------------------------------------------------------------------------
class MatchTeamStat(TimestampMixin, Base):
    """One team's performance in a single match (Understat team history row)."""

    __tablename__ = "match_team_stats"
    __table_args__ = (
        UniqueConstraint(
            "season_id", "team_id", "match_date", name="uq_team_stat_season_team_date"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[Optional[int]] = mapped_column(ForeignKey("matches.id"))
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    match_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    is_home: Mapped[Optional[bool]] = mapped_column(Boolean)
    goals: Mapped[Optional[int]] = mapped_column(Integer)
    conceded: Mapped[Optional[int]] = mapped_column(Integer)
    xg: Mapped[Optional[float]] = mapped_column(Float)
    xga: Mapped[Optional[float]] = mapped_column(Float)
    npxg: Mapped[Optional[float]] = mapped_column(Float)
    npxg_diff: Mapped[Optional[float]] = mapped_column(Float)
    ppda: Mapped[Optional[float]] = mapped_column(Float)
    ppda_allowed: Mapped[Optional[float]] = mapped_column(Float)
    deep: Mapped[Optional[int]] = mapped_column(Integer)
    deep_allowed: Mapped[Optional[int]] = mapped_column(Integer)
    xpts: Mapped[Optional[float]] = mapped_column(Float)
    points: Mapped[Optional[int]] = mapped_column(Integer)
    result: Mapped[Optional[str]] = mapped_column(String(1))  # w / d / l


class MatchPlayerStat(TimestampMixin, Base):
    """One player's line in a single match (Understat roster row)."""

    __tablename__ = "match_player_stats"
    __table_args__ = (
        UniqueConstraint("match_id", "player_id", name="uq_player_stat_match_player"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))

    minutes: Mapped[Optional[int]] = mapped_column(Integer)
    goals: Mapped[Optional[int]] = mapped_column(Integer)
    own_goals: Mapped[Optional[int]] = mapped_column(Integer)
    assists: Mapped[Optional[int]] = mapped_column(Integer)
    shots: Mapped[Optional[int]] = mapped_column(Integer)
    key_passes: Mapped[Optional[int]] = mapped_column(Integer)
    xg: Mapped[Optional[float]] = mapped_column(Float)
    xa: Mapped[Optional[float]] = mapped_column(Float)
    npg: Mapped[Optional[int]] = mapped_column(Integer)
    npxg: Mapped[Optional[float]] = mapped_column(Float)
    xg_chain: Mapped[Optional[float]] = mapped_column(Float)
    xg_buildup: Mapped[Optional[float]] = mapped_column(Float)
    position: Mapped[Optional[str]] = mapped_column(String(50))
    yellow_cards: Mapped[Optional[int]] = mapped_column(Integer)
    red_cards: Mapped[Optional[int]] = mapped_column(Integer)


class Shot(TimestampMixin, Base):
    __tablename__ = "shots"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_shot_source_ext"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))
    external_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    match_id: Mapped[Optional[int]] = mapped_column(ForeignKey("matches.id"))
    player_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"))
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))

    minute: Mapped[Optional[int]] = mapped_column(Integer)
    x: Mapped[Optional[float]] = mapped_column(Float)
    y: Mapped[Optional[float]] = mapped_column(Float)
    xg: Mapped[Optional[float]] = mapped_column(Float)
    result: Mapped[Optional[str]] = mapped_column(String(30))  # Goal, SavedShot, ...
    situation: Mapped[Optional[str]] = mapped_column(String(40))
    shot_type: Mapped[Optional[str]] = mapped_column(String(40))
    is_home: Mapped[Optional[bool]] = mapped_column(Boolean)
    last_action: Mapped[Optional[str]] = mapped_column(String(40))
    player_assisted: Mapped[Optional[str]] = mapped_column(String(150))


class Standing(TimestampMixin, Base):
    """Season-aggregated team table (derived from match history)."""

    __tablename__ = "standings"
    __table_args__ = (
        UniqueConstraint("season_id", "team_id", name="uq_standing_season_team"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id"), nullable=False
    )
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)

    position: Mapped[Optional[int]] = mapped_column(Integer)
    matches_played: Mapped[Optional[int]] = mapped_column(Integer)
    wins: Mapped[Optional[int]] = mapped_column(Integer)
    draws: Mapped[Optional[int]] = mapped_column(Integer)
    losses: Mapped[Optional[int]] = mapped_column(Integer)
    goals_for: Mapped[Optional[int]] = mapped_column(Integer)
    goals_against: Mapped[Optional[int]] = mapped_column(Integer)
    goal_diff: Mapped[Optional[int]] = mapped_column(Integer)
    points: Mapped[Optional[int]] = mapped_column(Integer)
    xg: Mapped[Optional[float]] = mapped_column(Float)
    xga: Mapped[Optional[float]] = mapped_column(Float)
    xg_diff: Mapped[Optional[float]] = mapped_column(Float)
    npxg: Mapped[Optional[float]] = mapped_column(Float)
    xpts: Mapped[Optional[float]] = mapped_column(Float)
    deep: Mapped[Optional[int]] = mapped_column(Integer)
    form: Mapped[Optional[str]] = mapped_column(String(20))  # e.g. "WWDLW"

    team: Mapped["Team"] = relationship()


class PlayerSeasonStat(TimestampMixin, Base):
    """Season-aggregated player line (Understat league player data)."""

    __tablename__ = "player_season_stats"
    __table_args__ = (
        UniqueConstraint("season_id", "player_id", name="uq_player_season"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id"), nullable=False
    )
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))

    games: Mapped[Optional[int]] = mapped_column(Integer)
    minutes: Mapped[Optional[int]] = mapped_column(Integer)
    goals: Mapped[Optional[int]] = mapped_column(Integer)
    assists: Mapped[Optional[int]] = mapped_column(Integer)
    shots: Mapped[Optional[int]] = mapped_column(Integer)
    key_passes: Mapped[Optional[int]] = mapped_column(Integer)
    xg: Mapped[Optional[float]] = mapped_column(Float)
    xa: Mapped[Optional[float]] = mapped_column(Float)
    npg: Mapped[Optional[int]] = mapped_column(Integer)
    npxg: Mapped[Optional[float]] = mapped_column(Float)
    xg_chain: Mapped[Optional[float]] = mapped_column(Float)
    xg_buildup: Mapped[Optional[float]] = mapped_column(Float)
    position: Mapped[Optional[str]] = mapped_column(String(50))
    yellow_cards: Mapped[Optional[int]] = mapped_column(Integer)
    red_cards: Mapped[Optional[int]] = mapped_column(Integer)

    player: Mapped["Player"] = relationship()
    team: Mapped[Optional["Team"]] = relationship()


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
class IngestionLog(TimestampMixin, Base):
    """Audit trail for every collection run."""

    __tablename__ = "ingestion_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))
    source_name: Mapped[Optional[str]] = mapped_column(String(50))
    sport: Mapped[Optional[str]] = mapped_column(String(50))
    entity: Mapped[Optional[str]] = mapped_column(String(50))
    league: Mapped[Optional[str]] = mapped_column(String(50))
    season: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="running")
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    error_message: Mapped[Optional[str]] = mapped_column(String(500))
    raw_path: Mapped[Optional[str]] = mapped_column(String(500))
