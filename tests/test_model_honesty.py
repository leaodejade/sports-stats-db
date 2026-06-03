"""Tests for phase D: backtest pricing, settlement check, closing line, CHECKs."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.analysis import data_quality as dq
from src.backtest import BacktestConfig, run_backtest
from src.models import Match, OddsSnapshot, Prediction
from src.services import betting_repository as br
from src.transformers import MarketResultDTO, OddsDTO, PredictionDTO

KICKOFF = datetime(2023, 10, 8, 16, 30)


def test_backtest_ignores_post_kickoff_price(session):
    """The default backtest must price from pre-kickoff snapshots only."""
    mid = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023", kickoff=KICKOFF)
    br.record_prediction(session, mid, PredictionDTO(
        model_name="m", model_version="1", market="1x2",
        selection="home", probability=0.60))
    # A fair pre-match price...
    br.record_odds(session, mid, OddsDTO(
        bookmaker="Pinnacle", market="1x2", selection="home", odd=2.0,
        captured_at=datetime(2023, 10, 8, 15, 0)))
    # ...and a tempting in-play price AFTER kickoff that must be ignored.
    br.record_odds(session, mid, OddsDTO(
        bookmaker="Pinnacle", market="1x2", selection="home", odd=10.0,
        captured_at=datetime(2023, 10, 8, 17, 0)))
    br.upsert_market_result(session, mid, MarketResultDTO(
        market="1x2", selection="home", outcome="won"))

    res = run_backtest(session, BacktestConfig(model_name="m", threshold=0.0))
    assert res.summary["bets"] == 1
    assert float(res.bets.iloc[0]["odd"]) == 2.0       # not 10.0
    assert res.summary["profit"] == pytest.approx(1.0)  # not 9.0


def test_settlement_validator_flags_wrong_outcome(session):
    mid = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    match = session.get(Match, mid)
    match.home_goals, match.away_goals = 2, 1       # home win, 3 goals total
    session.flush()

    br.upsert_market_result(session, mid, MarketResultDTO(
        market="1x2", selection="home", outcome="won"))      # correct
    br.upsert_market_result(session, mid, MarketResultDTO(
        market="1x2", selection="draw", outcome="won"))      # WRONG (should be lost)
    br.upsert_market_result(session, mid, MarketResultDTO(
        market="ou", selection="over", line=2.5, outcome="won"))  # correct (3>2.5)

    bad = dq.validate_market_settlements(session)
    assert len(bad) == 1
    row = bad.iloc[0]
    assert row["selection"] == "draw" and row["expected"] == "lost"


def test_mark_closing_odds_is_deterministic(session):
    mid = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023", kickoff=KICKOFF)
    for when, odd in [(datetime(2023, 10, 8, 14, 30), 2.0),
                      (datetime(2023, 10, 8, 15, 30), 1.9),   # last before kickoff
                      (datetime(2023, 10, 8, 17, 30), 5.0)]:  # after kickoff
        br.record_odds(session, mid, OddsDTO(
            bookmaker="Pinnacle", market="1x2", selection="home", odd=odd,
            captured_at=when))

    marked = br.mark_closing_odds(session, mid)
    assert marked == 1
    closing = session.scalars(
        select(OddsSnapshot).where(
            OddsSnapshot.match_id == mid, OddsSnapshot.is_closing.is_(True))
    ).all()
    assert len(closing) == 1
    assert closing[0].captured_at == datetime(2023, 10, 8, 15, 30)


def test_check_constraint_rejects_bad_probability(session):
    mid = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    market = br.get_or_create_market(session, "1x2")
    session.add(Prediction(
        match_id=mid, model_name="m", model_version="1", market_id=market.id,
        selection="home", probability=1.5, predicted_at=datetime(2023, 10, 8, 12, 0)))
    with pytest.raises(IntegrityError):
        session.flush()


def test_check_constraint_rejects_bad_odd(session):
    mid = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    market = br.get_or_create_market(session, "1x2")
    bk = br.get_or_create_bookmaker(session, "Pinnacle")
    session.add(OddsSnapshot(
        match_id=mid, bookmaker_id=bk.id, market_id=market.id, selection="home",
        odd=0.5, captured_at=datetime(2023, 10, 8, 12, 0)))
    with pytest.raises(IntegrityError):
        session.flush()
