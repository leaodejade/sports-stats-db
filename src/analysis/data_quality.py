"""Data quality validation checks."""

from typing import List, Optional, Tuple
import pandas as pd
from sqlalchemy import select, func, Float, String, desc
from sqlalchemy.orm import Session
from ..models.football import Match, MatchTeamStat, Shot
from ..models.betting import Market, MarketResult

def validate_xg_sums(session: Session, tolerance: float = 0.05) -> pd.DataFrame:
    """Check if the sum of shot xG approximately equals the match xG for each team."""

    # Calculate sum of shot xG for each match + team
    shots_stmt = (
        select(
            Shot.match_id,
            Shot.team_id,
            func.sum(Shot.xg).label("shot_xg_sum")
        )
        .group_by(Shot.match_id, Shot.team_id)
    ).subquery("shots_sum")

    # Get the expected xG from match_team_stats
    stmt = (
        select(
            MatchTeamStat.match_id,
            MatchTeamStat.team_id,
            MatchTeamStat.xg.label("team_xg"),
            shots_stmt.c.shot_xg_sum,
            func.abs(MatchTeamStat.xg - shots_stmt.c.shot_xg_sum).label("xg_diff")
        )
        .join(
            shots_stmt,
            (MatchTeamStat.match_id == shots_stmt.c.match_id) &
            (MatchTeamStat.team_id == shots_stmt.c.team_id)
        )
        .where(func.abs(MatchTeamStat.xg - shots_stmt.c.shot_xg_sum) > tolerance)
    )

    return pd.read_sql(stmt, session.connection())

def validate_goals_vs_shots(session: Session) -> pd.DataFrame:
    """Check if the match goals equal the count of shots with result='Goal'."""

    shots_stmt = (
        select(
            Shot.match_id,
            Shot.team_id,
            func.count(Shot.id).label("goals_from_shots")
        )
        .where(Shot.result == "Goal")
        .group_by(Shot.match_id, Shot.team_id)
    ).subquery("goals_shots")

    # Here we need to check Match vs MatchTeamStat, but Match has goals stored as strings inside MatchTeamStat typically.
    # Actually, Match has home_goals and away_goals. We will use MatchTeamStat to easily check by team.

    stmt = (
        select(
            MatchTeamStat.match_id,
            MatchTeamStat.team_id,
            MatchTeamStat.goals.label("team_goals"),
            func.coalesce(shots_stmt.c.goals_from_shots, 0).label("goals_from_shots")
        )
        .outerjoin(
            shots_stmt,
            (MatchTeamStat.match_id == shots_stmt.c.match_id) &
            (MatchTeamStat.team_id == shots_stmt.c.team_id)
        )
        .where(MatchTeamStat.goals != func.coalesce(shots_stmt.c.goals_from_shots, 0))
    )

    return pd.read_sql(stmt, session.connection())

def validate_match_has_score_and_xg(session: Session) -> pd.DataFrame:
    """Check that any match with is_result=True has non-null score and xG."""
    stmt = (
        select(
            Match.id.label("match_id"),
            Match.home_goals,
            Match.away_goals,
            Match.home_xg,
            Match.away_xg
        )
        .where(
            Match.is_result == True,
            (Match.home_goals.is_(None) | Match.away_goals.is_(None) |
             Match.home_xg.is_(None) | Match.away_xg.is_(None))
        )
    )
    return pd.read_sql(stmt, session.connection())

def validate_match_team_stats_linked(session: Session) -> pd.DataFrame:
    """Check if any MatchTeamStat with a date is missing its match_id."""
    stmt = (
        select(
            MatchTeamStat.id.label("stat_id"),
            MatchTeamStat.match_date,
            MatchTeamStat.team_id
        )
        .where(
            MatchTeamStat.match_date.is_not(None),
            MatchTeamStat.match_id.is_(None)
        )
    )
    return pd.read_sql(stmt, session.connection())

def _expected_outcome(
    code: str, selection: str, line: Optional[float], hg: int, ag: int
) -> Optional[str]:
    """Derive the correct outcome of a selection from the final score.

    Returns "won"/"lost"/"push" for derivable markets, or None to skip.
    """
    sel = (selection or "").strip().lower()
    total = hg + ag
    if code == "1x2":
        winner = "home" if hg > ag else "away" if ag > hg else "draw"
        return "won" if sel == winner else "lost"
    if code == "btts":
        both = hg > 0 and ag > 0
        if sel == "yes":
            return "won" if both else "lost"
        if sel == "no":
            return "won" if not both else "lost"
    if code == "ou" and line is not None:
        if total == line:
            return "push"
        if sel == "over":
            return "won" if total > line else "lost"
        if sel == "under":
            return "won" if total < line else "lost"
    return None


def validate_market_settlements(session: Session) -> pd.DataFrame:
    """Cross-check recorded ``market_results`` against the actual final score.

    Flags any settlement that disagrees with the score for derivable markets
    (1x2, BTTS, Over/Under) — catches a wrong liquidation before it skews P&L.
    """
    rows = []
    stmt = (
        select(MarketResult, Match, Market)
        .join(Match, Match.id == MarketResult.match_id)
        .join(Market, Market.id == MarketResult.market_id)
        .where(Match.home_goals.is_not(None), Match.away_goals.is_not(None))
    )
    for mr, match, market in session.execute(stmt).all():
        expected = _expected_outcome(
            market.code, mr.selection, mr.line, match.home_goals, match.away_goals
        )
        if expected is not None and expected != (mr.outcome or "").lower():
            rows.append({
                "match_id": mr.match_id, "market": market.code,
                "selection": mr.selection, "line": mr.line,
                "recorded": mr.outcome, "expected": expected,
            })
    return pd.DataFrame(
        rows, columns=["match_id", "market", "selection", "line", "recorded", "expected"]
    )


def run_all_validations(session: Session) -> pd.DataFrame:
    """Runs all validations and returns a summary DataFrame of violations."""
    violations = []

    xg_df = validate_xg_sums(session)
    if not xg_df.empty:
        for _, row in xg_df.iterrows():
            violations.append({
                "type": "xg_sum_mismatch",
                "match_id": row["match_id"],
                "team_id": row["team_id"],
                "description": f"Team xG {row['team_xg']} != sum of shot xG {row['shot_xg_sum']} (diff > tolerance)"
            })

    goals_df = validate_goals_vs_shots(session)
    if not goals_df.empty:
        for _, row in goals_df.iterrows():
            violations.append({
                "type": "goals_mismatch",
                "match_id": row["match_id"],
                "team_id": row["team_id"],
                "description": f"Match goals {row['team_goals']} != shot goals {row['goals_from_shots']}"
            })

    score_xg_df = validate_match_has_score_and_xg(session)
    if not score_xg_df.empty:
        for _, row in score_xg_df.iterrows():
            violations.append({
                "type": "missing_score_xg",
                "match_id": row["match_id"],
                "team_id": None,
                "description": f"Match {row['match_id']} has is_result=True but missing goals or xG"
            })

    linked_df = validate_match_team_stats_linked(session)
    if not linked_df.empty:
        for _, row in linked_df.iterrows():
            violations.append({
                "type": "unlinked_match_stat",
                "match_id": None,
                "team_id": row["team_id"],
                "description": f"MatchTeamStat {row['stat_id']} has date {row['match_date']} but no match_id"
            })

    return pd.DataFrame(violations)
