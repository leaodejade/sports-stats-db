"""Tests for odds maths / de-vig (audit phase D)."""

from __future__ import annotations

import pytest

from src.analysis import odds_math as om
from src.services import betting_repository as br
from src.transformers import OddsDTO


def test_implied_and_overround():
    assert om.implied_probability(2.0) == pytest.approx(0.5)
    assert om.implied_probability(0) is None
    ovr = om.overround({"home": 2.0, "draw": 4.0, "away": 4.0})
    assert ovr == pytest.approx(0.5 + 0.25 + 0.25 - 1.0)


def test_no_vig_sums_to_one_and_keeps_order():
    p = om.no_vig_probabilities({"home": 2.0, "draw": 3.5, "away": 4.0})
    assert sum(p.values()) == pytest.approx(1.0)
    assert p["home"] > p["draw"] > p["away"]
    # de-vigged prob is below the raw implied (margin removed)
    assert p["home"] < om.implied_probability(2.0)


def test_fair_odds_roundtrip():
    assert om.fair_odds(0.5) == pytest.approx(2.0)
    assert om.fair_odds(0) is None


def test_market_no_vig_from_current_odds(session):
    mid = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    for sel, odd in [("home", 2.0), ("draw", 3.5), ("away", 4.0)]:
        br.record_odds(session, mid, OddsDTO(
            bookmaker="Pinnacle", market="1x2", selection=sel, odd=odd))
    probs = om.market_no_vig(session, mid, "1x2", "Pinnacle")
    assert sum(probs.values()) == pytest.approx(1.0)
    assert probs["home"] > probs["away"]
