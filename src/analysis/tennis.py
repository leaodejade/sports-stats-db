"""Tennis analysis functions returning pandas DataFrames."""

import pandas as pd
from sqlalchemy import select, func, Float, cast, case
from sqlalchemy.orm import Session

from ..models.tennis import TennisMatch, TennisMatchStat, TennisPlayer, TennisSurface


from ..models.tennis import TennisMatch, TennisMatchStat, TennisPlayer, TennisSurface, TennisTournament

def serve_points_won_ranking(session: Session, min_serve_points: int = 100, limit: int = 20) -> pd.DataFrame:
    """Rank players by serve-points-won %."""
    empty_df = pd.DataFrame(columns=["rank", "player", "matches", "serve_points_won_pct"])

    stmt = (
        select(
            TennisPlayer.name.label("player"),
            func.count(TennisMatchStat.id).label("matches"),
            func.sum(TennisMatchStat.first_serve_points_won + TennisMatchStat.second_serve_points_won).label("points_won"),
            func.sum(TennisMatchStat.serve_points).label("points_attempted"),
        )
        .join(TennisMatchStat, TennisMatchStat.player_id == TennisPlayer.id)
        .group_by(TennisPlayer.id, TennisPlayer.name)
        .having(func.sum(TennisMatchStat.serve_points) >= min_serve_points)
    )
    df = pd.read_sql(stmt, session.connection())
    if df.empty:
        return empty_df

    df["serve_points_won_pct"] = (df["points_won"] / df["points_attempted"] * 100).round(2)
    df = df.sort_values("serve_points_won_pct", ascending=False).head(limit)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df[["rank", "player", "matches", "serve_points_won_pct"]]


def win_rate_by_surface(session: Session, player_name: str) -> pd.DataFrame:
    """Show a player's win rate broken down by surface."""
    empty_df = pd.DataFrame(columns=["surface", "matches", "wins", "losses", "win_rate"])

    player_id = session.scalar(select(TennisPlayer.id).where(TennisPlayer.name.ilike(f"%{player_name}%")).limit(1))
    if not player_id:
        return empty_df

    # A match has surface_id, or falls back to tournament.surface_id.
    # Use coalesce to get the effective surface.
    effective_surface = func.coalesce(TennisMatch.surface_id, TennisTournament.surface_id)

    stmt = (
        select(
            TennisSurface.name.label("surface"),
            func.count(TennisMatch.id).label("matches"),
            func.sum(case((TennisMatch.winner_id == player_id, 1), else_=0)).label("wins"),
            func.sum(case(( (TennisMatch.winner_id != player_id) & (TennisMatch.winner_id.is_not(None)), 1), else_=0)).label("losses"),
        )
        .select_from(TennisMatch)
        .join(TennisTournament, TennisTournament.id == TennisMatch.tournament_id)
        .join(TennisSurface, TennisSurface.id == effective_surface)
        .where(
            (TennisMatch.player1_id == player_id) | (TennisMatch.player2_id == player_id)
        )
        .group_by(TennisSurface.name)
    )

    df = pd.read_sql(stmt, session.connection())
    if df.empty:
        return empty_df

    df["win_rate"] = (df["wins"] / df["matches"]).astype(float).round(4)
    return df


def head_to_head(session: Session, player1_name: str, player2_name: str) -> pd.DataFrame:
    """Show head-to-head summary between two players."""
    empty_df = pd.DataFrame(columns=["player_a", "player_b", "matches", "wins_a", "wins_b"])

    p1 = session.scalar(select(TennisPlayer).where(TennisPlayer.name.ilike(f"%{player1_name}%")).limit(1))
    p2 = session.scalar(select(TennisPlayer).where(TennisPlayer.name.ilike(f"%{player2_name}%")).limit(1))

    if not p1 or not p2:
        return empty_df

    stmt = (
        select(
            func.count(TennisMatch.id).label("matches"),
            func.sum(case((TennisMatch.winner_id == p1.id, 1), else_=0)).label("wins_a"),
            func.sum(case((TennisMatch.winner_id == p2.id, 1), else_=0)).label("wins_b"),
        )
        .where(
            ((TennisMatch.player1_id == p1.id) & (TennisMatch.player2_id == p2.id)) |
            ((TennisMatch.player1_id == p2.id) & (TennisMatch.player2_id == p1.id))
        )
    )
    df = pd.read_sql(stmt, session.connection())
    if df.empty or df["matches"].iloc[0] == 0:
        return empty_df

    df.insert(0, "player_b", p2.name)
    df.insert(0, "player_a", p1.name)
    return df
