"""Build leakage-free pre-match features from per-match team history.

For a fixture H vs A kicking off at time D, every feature is computed from
``match_team_stats`` rows whose ``match_date`` is **strictly before D**. The
target match's own row (and therefore its xG, goals and result) is excluded by
construction, so the features never leak the outcome. ``matches.forecast_*`` is
never read here.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Match, MatchTeamStat, PrematchFeature

FEATURE_VERSION = "v1"


def _mean(values: list[Optional[float]]) -> Optional[float]:
    nums = [v for v in values if v is not None]
    return sum(nums) / len(nums) if nums else None


def _team_history(
    session: Session, team_id: int, before, limit: int
) -> list[MatchTeamStat]:
    """Most-recent-first team match rows strictly before ``before``."""
    if before is None:
        return []
    stmt = (
        select(MatchTeamStat)
        .where(MatchTeamStat.team_id == team_id, MatchTeamStat.match_date < before)
        .order_by(MatchTeamStat.match_date.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def _aggregate(history: list[MatchTeamStat], as_of) -> dict:
    n = len(history)
    if n == 0:
        return {"n": 0, "xgf": None, "xga": None, "form": None, "rest_days": None}
    rest_days = None
    last_date = history[0].match_date
    if as_of is not None and last_date is not None:
        rest_days = (as_of.date() - last_date.date()).days
    return {
        "n": n,
        "xgf": _round(_mean([h.xg for h in history])),
        "xga": _round(_mean([h.xga for h in history])),
        "form": _round(_mean([float(h.points) if h.points is not None else None
                              for h in history])),
        "rest_days": rest_days,
    }


def _round(value: Optional[float]) -> Optional[float]:
    return round(value, 4) if value is not None else None


def build_match_features(
    session: Session,
    match: Match,
    window: int = 5,
    version: str = FEATURE_VERSION,
) -> dict:
    """Return the pre-match feature dict for ``match`` (no DB write)."""
    as_of = match.match_datetime
    home = _aggregate(_team_history(session, match.home_team_id, as_of, window), as_of)
    away = _aggregate(_team_history(session, match.away_team_id, as_of, window), as_of)
    return {
        "match_id": match.id,
        "feature_set_version": version,
        "as_of": as_of,
        "window": window,
        "home_form": home["form"],
        "away_form": away["form"],
        "home_xgf": home["xgf"],
        "home_xga": home["xga"],
        "away_xgf": away["xgf"],
        "away_xga": away["xga"],
        "home_rest_days": home["rest_days"],
        "away_rest_days": away["rest_days"],
        "home_hist_n": home["n"],
        "away_hist_n": away["n"],
    }


def upsert_prematch_features(
    session: Session,
    match: Match,
    window: int = 5,
    version: str = FEATURE_VERSION,
) -> PrematchFeature:
    """Compute and persist features for one match (idempotent by match+version)."""
    data = build_match_features(session, match, window=window, version=version)
    row = session.scalar(
        select(PrematchFeature).where(
            PrematchFeature.match_id == match.id,
            PrematchFeature.feature_set_version == version,
        )
    )
    if row is None:
        row = PrematchFeature(match_id=match.id, feature_set_version=version)
        session.add(row)
    for key, value in data.items():
        if key in ("match_id", "feature_set_version"):
            continue
        setattr(row, key, value)
    session.flush()
    return row


def build_for_season(
    session: Session,
    season_id: int,
    window: int = 5,
    version: str = FEATURE_VERSION,
) -> int:
    """Build features for every finished match in a season. Returns the count."""
    matches = session.scalars(
        select(Match).where(Match.season_id == season_id, Match.is_result.is_(True))
    ).all()
    for match in matches:
        upsert_prematch_features(session, match, window=window, version=version)
    return len(matches)
