"""Tests for JSON ingestion of odds / predictions / results (audit phase 5)."""

from __future__ import annotations

from sqlalchemy import func, select

from src.backtest import BacktestConfig, run_backtest
from src.models import CurrentOdds, MarketResult, OddsSnapshot, Prediction
from src.services import json_ingest as ji


def test_ingest_odds_payload(session):
    payload = [{
        "home": "Arsenal", "away": "Chelsea", "league": "EPL", "season": "2023",
        "kickoff": "2023-10-08 16:30:00",
        "odds": [
            {"bookmaker": "Pinnacle", "market": "1x2", "selection": "home",
             "odd": 2.10, "is_closing": True, "captured_at": "2023-10-08 16:00:00"},
            {"bookmaker": "Bet365", "market": "1x2", "selection": "home", "odd": 2.20},
        ],
    }]
    counts = ji.ingest_odds_payload(session, payload)
    assert counts == {"fixtures": 1, "odds": 2}
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 2
    assert session.scalar(select(func.count()).select_from(CurrentOdds)) == 2


def test_ingest_predictions_and_results_payload(session):
    preds = [{
        "home": "Arsenal", "away": "Chelsea", "league": "EPL", "season": "2023",
        "model_name": "poisson", "model_version": "1.0",
        "predictions": [{"market": "1x2", "selection": "home", "probability": 0.55}],
    }]
    res = [{
        "home": "Arsenal", "away": "Chelsea", "league": "EPL", "season": "2023",
        "results": [{"market": "1x2", "selection": "home", "outcome": "won"}],
    }]
    pc = ji.ingest_predictions_payload(session, preds)
    rc = ji.ingest_results_payload(session, res)
    assert pc == {"fixtures": 1, "predictions": 1}
    assert rc == {"fixtures": 1, "results": 1}

    pred = session.scalar(select(Prediction))
    assert pred.fair_odd is not None  # 1/0.55
    assert session.scalar(select(func.count()).select_from(MarketResult)) == 1


def test_json_roundtrip_feeds_a_backtest(session):
    """Odds + prediction + result loaded from JSON should drive a value bet."""
    fixture = {"home": "Arsenal", "away": "Chelsea", "league": "EPL", "season": "2023"}
    ji.ingest_odds_payload(session, [{
        **fixture,
        "odds": [{"bookmaker": "Pinnacle", "market": "1x2", "selection": "home",
                  "odd": 2.0, "is_closing": True}],
    }])
    ji.ingest_predictions_payload(session, [{
        **fixture, "model_name": "m", "model_version": "1",
        "predictions": [{"market": "1x2", "selection": "home", "probability": 0.60}],
    }])
    ji.ingest_results_payload(session, [{
        **fixture, "results": [{"market": "1x2", "selection": "home", "outcome": "won"}],
    }])

    res = run_backtest(session, BacktestConfig(model_name="m", threshold=0.0))
    assert res.summary["bets"] == 1
    assert res.summary["profit"] == 1.0  # EV +0.2, won at odd 2.0, stake 1


def test_resolve_is_shared_across_payloads(session):
    """The same fixture across odds/predictions maps to one match (no dupes)."""
    from src.models import Match

    fixture = {"home": "Arsenal", "away": "Chelsea", "league": "EPL", "season": "2023"}
    ji.ingest_odds_payload(session, [{**fixture, "odds": [
        {"bookmaker": "Pinnacle", "market": "1x2", "selection": "home", "odd": 2.0}]}])
    ji.ingest_predictions_payload(session, [{**fixture, "model_name": "m",
        "model_version": "1", "predictions": [
        {"market": "1x2", "selection": "home", "probability": 0.5}]}])
    assert session.scalar(select(func.count()).select_from(Match)) == 1
