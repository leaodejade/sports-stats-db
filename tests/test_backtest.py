"""Tests for the backtest engine and calibration (audit phase 3)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.analysis import calibration as cal
from src.backtest import BacktestConfig, run_backtest, summarize_by
from src.models import BetDecision
from src.services import betting_repository as br
from src.transformers import MarketResultDTO, OddsDTO, PredictionDTO


def _add_case(session, home, away, prob, odd, outcome=None):
    """One match with a 1x2 home price, a prediction and (optional) result."""
    mid = br.resolve_match(session, home, away, "EPL", "2023")
    br.record_odds(session, mid, OddsDTO(
        bookmaker="Pinnacle", market="1x2", selection="home", odd=odd,
        is_closing=True))
    br.record_prediction(session, mid, PredictionDTO(
        model_name="test", model_version="1.0", market="1x2",
        selection="home", probability=prob))
    if outcome is not None:
        br.upsert_market_result(session, mid, MarketResultDTO(
            market="1x2", selection="home", outcome=outcome))
    return mid


@pytest.fixture()
def seeded(session):
    # EV>0 & won, EV>0 & lost, EV<0, EV>0 but no result.
    _add_case(session, "Arsenal", "Chelsea", prob=0.60, odd=2.0, outcome="won")
    _add_case(session, "Liverpool", "Everton", prob=0.50, odd=2.5, outcome="lost")
    _add_case(session, "Tottenham", "Fulham", prob=0.40, odd=2.0, outcome="lost")
    _add_case(session, "Newcastle United", "Brentford", prob=0.70, odd=2.0)  # no result
    return session


def test_backtest_places_only_positive_ev_with_results(seeded):
    res = run_backtest(seeded, BacktestConfig(model_name="test", threshold=0.0))
    assert res.summary["bets"] == 2            # Arsenal + Liverpool
    assert res.summary["staked"] == 2.0
    assert res.summary["profit"] == pytest.approx(0.0)  # +1 and -1
    assert res.summary["hit_rate_pct"] == 50.0


def test_backtest_decisions_capture_rejections(seeded):
    res = run_backtest(seeded, BacktestConfig(model_name="test", threshold=0.0))
    reasons = set(res.decisions["reason"])
    assert "value_bet" in reasons
    assert "ev_below_threshold" in reasons   # Tottenham (EV -0.2)
    assert "no_result" in reasons            # Newcastle (no settlement)


def test_backtest_threshold_filters_more(seeded):
    res = run_backtest(seeded, BacktestConfig(model_name="test", threshold=0.21))
    # Only Liverpool (EV 0.25) clears 0.21; Arsenal (EV 0.20) does not.
    assert res.summary["bets"] == 1


def test_persist_decisions_writes_audit_rows(seeded):
    run_backtest(seeded, BacktestConfig(model_name="test", run_label="r1"),
                 persist_decisions=True)
    n = seeded.scalar(select(func.count()).select_from(BetDecision))
    assert n == 4  # one decision per prediction considered


def test_summarize_by_dimensions(seeded):
    res = run_backtest(seeded, BacktestConfig(model_name="test"))
    by_league = summarize_by(res.bets, "league")
    assert by_league.loc[0, "league"] == "EPL"
    assert int(by_league.loc[0, "bets"]) == 2
    by_bucket = summarize_by(res.bets, "odd_bucket")
    assert int(by_bucket["bets"].sum()) == 2


def test_calibration_metrics(seeded):
    df = cal.prediction_outcomes(seeded, "test")
    assert len(df) == 3  # Arsenal(won), Liverpool(lost), Tottenham(lost)
    # Brier = mean((.6-1)^2, (.5-0)^2, (.4-0)^2) = (.16+.25+.16)/3
    assert cal.brier_score(df) == pytest.approx((0.16 + 0.25 + 0.16) / 3, abs=1e-4)
    summ = cal.calibration_summary(seeded, "test")
    assert summ["n"] == 3 and summ["log_loss"] is not None

    table = cal.calibration_table(df)
    assert int(table["n"].sum()) == 3
