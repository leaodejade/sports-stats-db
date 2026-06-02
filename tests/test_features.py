"""Tests for the pre-match feature store, including a leakage guard."""

from __future__ import annotations

from sqlalchemy import select

from src.features import build_for_season, build_match_features, upsert_prematch_features
from src.models import Match, MatchTeamStat, PrematchFeature, Season


def _matches_in_order(session):
    """The two sample matches (Arsenal v City, then City v Arsenal), by date."""
    return list(
        session.scalars(
            select(Match).where(Match.is_result.is_(True)).order_by(Match.match_datetime)
        ).all()
    )


def test_earliest_match_has_no_history(populated):
    from src.database import get_session_factory

    session = get_session_factory(populated)()
    try:
        first = _matches_in_order(session)[0]
        feats = build_match_features(session, first)
        # Nothing happened before the first match -> empty history, no xG features.
        assert feats["home_hist_n"] == 0
        assert feats["away_hist_n"] == 0
        assert feats["home_xgf"] is None
        assert feats["away_xgf"] is None
    finally:
        session.close()


def test_later_match_uses_only_prior_data(populated):
    from src.database import get_session_factory

    session = get_session_factory(populated)()
    try:
        second = _matches_in_order(session)[1]
        feats = build_match_features(session, second)
        # One prior match exists for each side -> features are populated.
        assert feats["home_hist_n"] == 1
        assert feats["away_hist_n"] == 1
        assert feats["home_xgf"] is not None
        assert feats["away_xgf"] is not None
    finally:
        session.close()


def test_features_are_stable_when_target_match_outcome_is_tampered(populated):
    """LEAKAGE GUARD: changing the target match's own result/xG/forecast must
    NOT change its pre-match features. If it does, a feature is leaking."""
    from src.database import get_session_factory

    session = get_session_factory(populated)()
    try:
        second = _matches_in_order(session)[1]
        before = build_match_features(session, second)

        # Tamper with everything that describes the target match's outcome.
        second.home_goals, second.away_goals = 99, 0
        second.home_xg, second.away_xg = 9.9, 0.0
        second.forecast_w, second.forecast_d, second.forecast_l = 1.0, 0.0, 0.0
        own_rows = session.scalars(
            select(MatchTeamStat).where(
                MatchTeamStat.match_date == second.match_datetime
            )
        ).all()
        for row in own_rows:
            row.xg, row.xga, row.goals, row.conceded = 9.9, 0.0, 99, 0
            row.points, row.result = 3, "w"
        session.flush()

        after = build_match_features(session, second)
        assert before == after, "pre-match features changed after tampering the result -> LEAKAGE"
    finally:
        session.close()


def test_upsert_and_build_for_season_are_idempotent(populated):
    from src.database import get_session_factory

    session = get_session_factory(populated)()
    try:
        season = session.scalars(select(Season)).first()
        n1 = build_for_season(session, season.id)
        n2 = build_for_season(session, season.id)
        assert n1 == n2 == 2
        rows = session.scalars(select(PrematchFeature)).all()
        assert len(rows) == 2  # no duplicates on re-run

        # Stored row matches a fresh build for the later match.
        second = _matches_in_order(session)[1]
        stored = session.scalar(
            select(PrematchFeature).where(PrematchFeature.match_id == second.id)
        )
        fresh = build_match_features(session, second)
        assert stored.home_xgf == fresh["home_xgf"]
        assert stored.away_form == fresh["away_form"]
    finally:
        session.close()
