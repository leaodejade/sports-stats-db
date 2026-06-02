"""Tests for the betting data layer (network-free, isolated SQLite)."""

from __future__ import annotations

from datetime import datetime

import pytest

from sqlalchemy import select

from src.analysis import betting as ba
from src.models import Bookmaker, CurrentOdds, Market, OddsSnapshot
from src.services import betting_repository as br
from src.transformers import BetDTO, MarketResultDTO, OddsDTO, PredictionDTO


# ---------------------------------------------------------------------------
# Seed / schema
# ---------------------------------------------------------------------------
def test_seed_creates_markets_and_bookmakers(session):
    assert session.scalar(select(Market).where(Market.code == "1x2")) is not None
    assert session.scalar(select(Market).where(Market.code == "ah")) is not None
    assert session.scalar(select(Bookmaker).where(Bookmaker.name == "Pinnacle")) is not None


def test_resolve_match_is_idempotent(session):
    m1 = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    m2 = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    assert m1 == m2


# ---------------------------------------------------------------------------
# Odds
# ---------------------------------------------------------------------------
def test_record_odds_writes_snapshot_and_current(session):
    match_id = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    br.record_odds(session, match_id, OddsDTO(
        bookmaker="Pinnacle", market="1x2", selection="home", odd=2.00,
        captured_at=datetime(2023, 10, 8, 10, 0)))

    snaps = session.scalars(select(OddsSnapshot)).all()
    assert len(snaps) == 1
    assert snaps[0].implied_prob == pytest.approx(0.5)

    current = session.scalar(select(CurrentOdds))
    assert current.odd == 2.00


def test_record_odds_current_tracks_latest_only(session):
    match_id = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    br.record_odds(session, match_id, OddsDTO(
        bookmaker="Pinnacle", market="1x2", selection="home", odd=2.00,
        captured_at=datetime(2023, 10, 8, 10, 0)))
    br.record_odds(session, match_id, OddsDTO(
        bookmaker="Pinnacle", market="1x2", selection="home", odd=1.80,
        is_closing=True, captured_at=datetime(2023, 10, 8, 16, 0)))

    # Two snapshots in history, one current row reflecting the latest price.
    assert len(session.scalars(select(OddsSnapshot)).all()) == 2
    currents = session.scalars(select(CurrentOdds)).all()
    assert len(currents) == 1
    assert currents[0].odd == 1.80


def test_overround_and_best_odds(session):
    match_id = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    for sel, odd in [("home", 2.0), ("draw", 3.5), ("away", 4.0)]:
        br.record_odds(session, match_id, OddsDTO(
            bookmaker="Pinnacle", market="1x2", selection=sel, odd=odd))
    # A second book offers a better home price.
    br.record_odds(session, match_id, OddsDTO(
        bookmaker="Bet365", market="1x2", selection="home", odd=2.20))

    over = ba.market_overround(session, match_id, "Pinnacle", "1x2")
    assert over == pytest.approx(1/2.0 + 1/3.5 + 1/4.0 - 1.0, abs=1e-3)

    best = ba.best_odds(session, match_id)
    home_best = best[best.selection == "home"].iloc[0]
    assert home_best["odd"] == 2.20
    assert home_best["bookmaker"] == "Bet365"


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------
def test_record_prediction_computes_fair_odd_and_edge(session):
    match_id = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    br.record_odds(session, match_id, OddsDTO(
        bookmaker="Pinnacle", market="1x2", selection="home", odd=2.50))
    pred = br.record_prediction(session, match_id, PredictionDTO(
        model_name="poisson", model_version="1.0", market="1x2",
        selection="home", probability=0.50))

    assert pred.fair_odd == pytest.approx(2.0)
    # edge = p * best_odd - 1 = 0.5 * 2.5 - 1 = 0.25
    assert pred.edge == pytest.approx(0.25)


def test_record_prediction_is_idempotent(session):
    match_id = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    dto = PredictionDTO(model_name="m", model_version="1", market="1x2",
                        selection="home", probability=0.4)
    p1 = br.record_prediction(session, match_id, dto)
    dto2 = PredictionDTO(model_name="m", model_version="1", market="1x2",
                         selection="home", probability=0.6)
    p2 = br.record_prediction(session, match_id, dto2)
    assert p1.id == p2.id
    assert p2.probability == 0.6


# ---------------------------------------------------------------------------
# Bankroll + simulated bets
# ---------------------------------------------------------------------------
def test_place_and_settle_winning_bet_moves_bankroll(session):
    match_id = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    br.deposit(session, 100.0)
    assert br.current_balance(session) == 100.0

    bet = br.place_bet(session, match_id, BetDTO(
        market="1x2", selection="home", odd_taken=2.0, stake=10.0,
        bookmaker="Pinnacle"))
    assert br.current_balance(session) == 90.0  # stake debited

    br.settle_bet(session, bet.id, "won")
    assert bet.status == "won"
    assert bet.pnl == pytest.approx(10.0)
    assert br.current_balance(session) == 110.0  # 90 + return(20)


def test_settle_losing_bet(session):
    match_id = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    br.deposit(session, 100.0)
    bet = br.place_bet(session, match_id, BetDTO(
        market="1x2", selection="home", odd_taken=2.0, stake=10.0))
    br.settle_bet(session, bet.id, "lost")
    assert bet.pnl == pytest.approx(-10.0)
    assert br.current_balance(session) == 90.0


def test_cannot_settle_twice(session):
    match_id = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    br.deposit(session, 100.0)
    bet = br.place_bet(session, match_id, BetDTO(
        market="1x2", selection="home", odd_taken=2.0, stake=10.0))
    br.settle_bet(session, bet.id, "won")
    with pytest.raises(ValueError):
        br.settle_bet(session, bet.id, "won")


def test_pnl_summary(session):
    match_id = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    br.deposit(session, 100.0)
    b1 = br.place_bet(session, match_id, BetDTO(
        market="1x2", selection="home", odd_taken=2.0, stake=10.0))
    b2 = br.place_bet(session, match_id, BetDTO(
        market="1x2", selection="away", odd_taken=3.0, stake=10.0))
    br.settle_bet(session, b1.id, "won")   # +10
    br.settle_bet(session, b2.id, "lost")  # -10

    summary = ba.pnl_summary(session)
    assert summary["bets"] == 2
    assert summary["staked"] == 20.0
    assert summary["profit"] == pytest.approx(0.0)
    assert summary["hit_rate_pct"] == 50.0


# ---------------------------------------------------------------------------
# Settlement + CLV
# ---------------------------------------------------------------------------
def test_market_result_upsert(session):
    match_id = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    r1 = br.upsert_market_result(session, match_id, MarketResultDTO(
        market="ou", selection="over", line=2.5, outcome="won", result_value=3))
    r2 = br.upsert_market_result(session, match_id, MarketResultDTO(
        market="ou", selection="over", line=2.5, outcome="lost"))
    assert r1.id == r2.id
    assert r2.outcome == "lost"


def test_clv_report_beating_the_close(session):
    match_id = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    # We took 2.10; the line closed shorter at 1.90 -> positive CLV.
    br.place_bet(session, match_id, BetDTO(
        market="1x2", selection="home", odd_taken=2.10, stake=1.0))
    br.record_odds(session, match_id, OddsDTO(
        bookmaker="Pinnacle", market="1x2", selection="home", odd=1.90,
        is_closing=True))

    summary = ba.clv_summary(session)
    assert summary["bets_with_closing"] == 1
    assert summary["mean_clv"] == pytest.approx(2.10 / 1.90 - 1.0, abs=1e-4)
    assert summary["pct_positive"] == 100.0
