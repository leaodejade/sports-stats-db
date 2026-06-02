"""Analytical queries over the football schema, returned as pandas DataFrames.

Functions are pure reads: they take a SQLAlchemy ``Session`` plus identifiers
(league code, season, team/player name) and never mutate the database. The CLI
and notebooks consume these directly.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Competition,
    MatchTeamStat,
    Player,
    PlayerSeasonStat,
    Season,
    Standing,
    Team,
)


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------
def resolve_season(
    session: Session, league: str, season: str
) -> Optional[Season]:
    """Resolve a (league code, external season) pair to a ``Season`` row."""
    competition = session.scalar(select(Competition).where(Competition.code == league))
    if competition is None:
        return None
    return session.scalar(
        select(Season).where(
            Season.competition_id == competition.id,
            Season.external_season == str(season),
        )
    )


def _df(rows, columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def _with_rank(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df


# ---------------------------------------------------------------------------
# Team-level tables
# ---------------------------------------------------------------------------
def xg_table(session: Session, league: str, season: str) -> pd.DataFrame:
    """Full season table sorted by points, with real and expected metrics."""
    season_obj = resolve_season(session, league, season)
    if season_obj is None:
        return _df([], ["position", "team", "mp", "w", "d", "l", "gf", "ga",
                        "gd", "pts", "xg", "xga", "xgd", "xpts", "form"])
    stmt = (
        select(
            Standing.position, Team.name, Standing.matches_played,
            Standing.wins, Standing.draws, Standing.losses,
            Standing.goals_for, Standing.goals_against, Standing.goal_diff,
            Standing.points, Standing.xg, Standing.xga, Standing.xg_diff,
            Standing.xpts, Standing.form,
        )
        .join(Team, Team.id == Standing.team_id)
        .where(Standing.season_id == season_obj.id)
        .order_by(Standing.position.asc().nullslast(), Standing.points.desc())
    )
    return _df(
        session.execute(stmt).all(),
        ["position", "team", "mp", "w", "d", "l", "gf", "ga", "gd",
         "pts", "xg", "xga", "xgd", "xpts", "form"],
    )


def team_xg_ranking(session: Session, league: str, season: str) -> pd.DataFrame:
    """Teams ranked by expected goals created (attack quality)."""
    season_obj = resolve_season(session, league, season)
    if season_obj is None:
        return _df([], ["rank", "team", "xg", "goals_for", "mp"])
    stmt = (
        select(Team.name, Standing.xg, Standing.goals_for, Standing.matches_played)
        .join(Team, Team.id == Standing.team_id)
        .where(Standing.season_id == season_obj.id)
        .order_by(Standing.xg.desc().nullslast())
    )
    return _with_rank(_df(session.execute(stmt).all(),
                          ["team", "xg", "goals_for", "mp"]))


def team_xga_ranking(session: Session, league: str, season: str) -> pd.DataFrame:
    """Teams ranked by fewest expected goals conceded (defensive quality)."""
    season_obj = resolve_season(session, league, season)
    if season_obj is None:
        return _df([], ["rank", "team", "xga", "goals_against", "mp"])
    stmt = (
        select(Team.name, Standing.xga, Standing.goals_against, Standing.matches_played)
        .join(Team, Team.id == Standing.team_id)
        .where(Standing.season_id == season_obj.id)
        .order_by(Standing.xga.asc().nullslast())
    )
    return _with_rank(_df(session.execute(stmt).all(),
                          ["team", "xga", "goals_against", "mp"]))


def team_xg_diff(session: Session, league: str, season: str) -> pd.DataFrame:
    """Teams ranked by xG balance (xG - xGA)."""
    season_obj = resolve_season(session, league, season)
    if season_obj is None:
        return _df([], ["rank", "team", "xg", "xga", "xg_diff"])
    stmt = (
        select(Team.name, Standing.xg, Standing.xga, Standing.xg_diff)
        .join(Team, Team.id == Standing.team_id)
        .where(Standing.season_id == season_obj.id)
        .order_by(Standing.xg_diff.desc().nullslast())
    )
    return _with_rank(_df(session.execute(stmt).all(),
                          ["team", "xg", "xga", "xg_diff"]))


def real_vs_expected(session: Session, league: str, season: str) -> pd.DataFrame:
    """Compare actual points/goals against expected (xPTS / xG)."""
    season_obj = resolve_season(session, league, season)
    cols = ["team", "points", "xpts", "pts_diff", "goals_for", "xg", "goals_vs_xg"]
    if season_obj is None:
        return _df([], cols)
    stmt = (
        select(Team.name, Standing.points, Standing.xpts, Standing.goals_for, Standing.xg)
        .join(Team, Team.id == Standing.team_id)
        .where(Standing.season_id == season_obj.id)
    )
    df = _df(session.execute(stmt).all(),
             ["team", "points", "xpts", "goals_for", "xg"])
    if df.empty:
        return _df([], cols)
    df["pts_diff"] = (df["points"] - df["xpts"]).round(2)
    df["goals_vs_xg"] = (df["goals_for"] - df["xg"]).round(2)
    df = df[["team", "points", "xpts", "pts_diff", "goals_for", "xg", "goals_vs_xg"]]
    return df.sort_values("pts_diff", ascending=False).reset_index(drop=True)


def recent_form(
    session: Session, team: str, season: str, n: int = 5
) -> pd.DataFrame:
    """Last ``n`` matches for a team in a given season (most recent first)."""
    cols = ["date", "home", "result", "goals", "conceded", "xg", "xga", "xpts", "points"]
    stmt = (
        select(
            MatchTeamStat.match_date, MatchTeamStat.is_home, MatchTeamStat.result,
            MatchTeamStat.goals, MatchTeamStat.conceded, MatchTeamStat.xg,
            MatchTeamStat.xga, MatchTeamStat.xpts, MatchTeamStat.points,
        )
        .join(Team, Team.id == MatchTeamStat.team_id)
        .join(Season, Season.id == MatchTeamStat.season_id)
        .where(Team.name.ilike(f"%{team}%"), Season.external_season == str(season))
        .order_by(MatchTeamStat.match_date.desc().nullslast())
        .limit(n)
    )
    return _df(session.execute(stmt).all(), cols)


# ---------------------------------------------------------------------------
# Player-level tables
# ---------------------------------------------------------------------------
_PLAYER_COLUMNS = [
    "player", "team", "season", "league", "games", "minutes", "goals",
    "assists", "xg", "xa", "npg", "npxg", "shots",
]


def _player_season_df(
    session: Session,
    league: Optional[str] = None,
    season: Optional[str] = None,
    player_name: Optional[str] = None,
) -> pd.DataFrame:
    stmt = (
        select(
            Player.name, Team.name, Season.label, Competition.code,
            PlayerSeasonStat.games, PlayerSeasonStat.minutes, PlayerSeasonStat.goals,
            PlayerSeasonStat.assists, PlayerSeasonStat.xg, PlayerSeasonStat.xa,
            PlayerSeasonStat.npg, PlayerSeasonStat.npxg, PlayerSeasonStat.shots,
        )
        .join(Player, Player.id == PlayerSeasonStat.player_id)
        .join(Season, Season.id == PlayerSeasonStat.season_id)
        .join(Competition, Competition.id == PlayerSeasonStat.competition_id)
        .outerjoin(Team, Team.id == PlayerSeasonStat.team_id)
    )
    if league is not None:
        stmt = stmt.where(Competition.code == league)
    if season is not None:
        stmt = stmt.where(Season.external_season == str(season))
    if player_name is not None:
        stmt = stmt.where(Player.name.ilike(f"%{player_name}%"))

    df = _df(session.execute(stmt).all(), _PLAYER_COLUMNS)
    for col in ("goals", "assists", "xg", "xa", "npg", "npxg", "shots"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def top_players_by_xg(
    session: Session,
    league: Optional[str] = None,
    season: Optional[str] = None,
    limit: int = 20,
) -> pd.DataFrame:
    df = _player_season_df(session, league, season)
    df = df.sort_values("xg", ascending=False).head(limit)
    return _with_rank(df[["player", "team", "season", "goals", "xg", "shots"]])


def top_players_by_xa(
    session: Session,
    league: Optional[str] = None,
    season: Optional[str] = None,
    limit: int = 20,
) -> pd.DataFrame:
    df = _player_season_df(session, league, season)
    df = df.sort_values("xa", ascending=False).head(limit)
    return _with_rank(df[["player", "team", "season", "assists", "xa"]])


def player_overperformers(
    session: Session,
    league: Optional[str] = None,
    season: Optional[str] = None,
    limit: int = 20,
    min_minutes: int = 450,
) -> pd.DataFrame:
    """Players scoring more than expected (goals - xG, highest first)."""
    return _performance(session, league, season, limit, min_minutes, ascending=False)


def player_underperformers(
    session: Session,
    league: Optional[str] = None,
    season: Optional[str] = None,
    limit: int = 20,
    min_minutes: int = 450,
) -> pd.DataFrame:
    """Players scoring fewer than expected (goals - xG, lowest first)."""
    return _performance(session, league, season, limit, min_minutes, ascending=True)


def _performance(
    session: Session,
    league: Optional[str],
    season: Optional[str],
    limit: int,
    min_minutes: int,
    ascending: bool,
) -> pd.DataFrame:
    df = _player_season_df(session, league, season)
    if df.empty:
        return _df([], ["rank", "player", "team", "season", "goals", "xg", "g_minus_xg"])
    df = df[df["minutes"].fillna(0) >= min_minutes].copy()
    df["g_minus_xg"] = (df["goals"] - df["xg"]).round(2)
    df = df.sort_values("g_minus_xg", ascending=ascending).head(limit)
    return _with_rank(df[["player", "team", "season", "goals", "xg", "g_minus_xg"]])


# ---------------------------------------------------------------------------
# Single-entity lookups (CLI: team-stats / player-stats)
# ---------------------------------------------------------------------------
def team_season_stats(
    session: Session, team: str, season: str
) -> pd.DataFrame:
    """Season standing(s) for a team matched by (partial) name."""
    stmt = (
        select(
            Competition.code, Season.label, Team.name, Standing.position,
            Standing.matches_played, Standing.wins, Standing.draws, Standing.losses,
            Standing.goals_for, Standing.goals_against, Standing.points,
            Standing.xg, Standing.xga, Standing.xg_diff, Standing.xpts, Standing.form,
        )
        .join(Team, Team.id == Standing.team_id)
        .join(Season, Season.id == Standing.season_id)
        .join(Competition, Competition.id == Standing.competition_id)
        .where(Team.name.ilike(f"%{team}%"), Season.external_season == str(season))
    )
    return _df(
        session.execute(stmt).all(),
        ["league", "season", "team", "position", "mp", "w", "d", "l", "gf",
         "ga", "pts", "xg", "xga", "xgd", "xpts", "form"],
    )


def player_stats(session: Session, player: str) -> pd.DataFrame:
    """All season lines for a player matched by (partial) name."""
    df = _player_season_df(session, player_name=player)
    if df.empty:
        return df
    return df.sort_values(["player", "season"]).reset_index(drop=True)
