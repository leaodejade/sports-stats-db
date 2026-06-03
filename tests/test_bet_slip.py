"""Tests for the bet-slip pre-flight gate (audit phase C)."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select

from src.models import BetDecision, BetSlipLeg
from src.services import bet_slip as bs
from src.services import betting_repository as br
from src.services import odds_ingest as oi
from src.transformers import OddsDTO, PredictionDTO

KICKOFF = datetime(2023, 10, 8, 16, 30)
NOW = datetime(2023, 10, 8, 15, 0)        # before kickoff
CAPTURED = "2023-10-08 14:00:00"


def _cap(home, away, h, d, a):
    return {"bookmaker": "Pinnacle", "home": home, "away": away,
            "league": "EPL", "season": "2023",
            "captured_at": CAPTURED, "kickoff": "2023-10-08 16:30:00",
            "market": "1x2",
            "selections": [{"selection": "home", "odd": h},
                           {"selection": "draw", "odd": d},
                           {"selection": "away", "odd": a}]}


@pytest.fixture()
def gated(session):
    """Two matches with full 1x2 markets promoted through the OCR gate."""
    mid1 = br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023", kickoff=KICKOFF)
    mid2 = br.resolve_match(session, "Liverpool", "Everton", "EPL", "2023", kickoff=KICKOFF)
    oi.ingest_capture(session, {"captures": [
        _cap("Arsenal", "Chelsea", 2.0, 3.5, 4.0),
        _cap("Liverpool", "Everton", 2.5, 3.4, 2.9),
    ]})
    return session, mid1, mid2


def _legs(slip_id, session):
    return session.scalars(
        select(BetSlipLeg).where(BetSlipLeg.slip_id == slip_id)
    ).all()


def test_valid_slip_is_ready_with_combined_odd(gated):
    session, mid1, mid2 = gated
    slip = bs.build_bet_slip(session, legs=[
        {"match_id": mid1, "market": "1x2", "selection": "home"},
        {"match_id": mid2, "market": "1x2", "selection": "home"},
    ], stake=10, now=NOW)
    assert slip.status == "ready"
    assert slip.combined_odd == pytest.approx(2.0 * 2.5)


def test_missing_odds_rejects_the_whole_slip(gated):
    session, mid1, _ = gated
    slip = bs.build_bet_slip(session, legs=[
        {"match_id": mid1, "market": "1x2", "selection": "home"},
        {"match_id": mid1, "market": "ou", "selection": "over", "line": 2.5},  # not priced
    ], now=NOW)
    assert slip.status == "rejected"
    reasons = {leg.reason for leg in _legs(slip.id, session)}
    assert "no_odds" in reasons
    # rejection is audited in bet_decisions
    assert session.scalar(
        select(func.count()).select_from(BetDecision)
        .where(BetDecision.run_label == f"slip:{slip.id}")
    ) >= 1


def test_require_gate_blocks_unvalidated_odds(gated):
    session, mid1, _ = gated
    # btts odds written directly (NOT through the OCR gate).
    for sel, odd in [("yes", 1.80), ("no", 2.00)]:
        br.record_odds(session, mid1, OddsDTO(
            bookmaker="Bet365", market="btts", selection=sel, odd=odd,
            captured_at=datetime(2023, 10, 8, 14, 0)))

    strict = bs.build_bet_slip(session, legs=[
        {"match_id": mid1, "market": "btts", "selection": "yes"}],
        require_gate=True, now=NOW)
    assert strict.status == "rejected"
    assert _legs(strict.id, session)[0].reason == "unvalidated_odds"

    loose = bs.build_bet_slip(session, legs=[
        {"match_id": mid1, "market": "btts", "selection": "yes"}],
        require_gate=False, now=NOW)
    assert loose.status == "ready"


def test_after_kickoff_is_rejected(gated):
    session, mid1, _ = gated
    slip = bs.build_bet_slip(session, legs=[
        {"match_id": mid1, "market": "1x2", "selection": "home"}],
        now=datetime(2023, 10, 8, 17, 0))  # past kickoff
    assert slip.status == "rejected"
    assert _legs(slip.id, session)[0].reason == "after_kickoff"


def test_below_min_edge_is_rejected(gated):
    session, mid1, _ = gated
    br.record_prediction(session, mid1, PredictionDTO(
        model_name="m", model_version="1", market="1x2",
        selection="home", probability=0.40))  # 0.40*2.0-1 = -0.2 edge
    slip = bs.build_bet_slip(session, legs=[
        {"match_id": mid1, "market": "1x2", "selection": "home"}],
        model_name="m", model_version="1", min_edge=0.0, now=NOW)
    assert slip.status == "rejected"
    assert _legs(slip.id, session)[0].reason == "below_min_edge"


def test_stale_odds_rejected_by_freshness(gated):
    session, mid1, _ = gated
    slip = bs.build_bet_slip(session, legs=[
        {"match_id": mid1, "market": "1x2", "selection": "home"}],
        freshness_seconds=1800, now=NOW)  # captured 14:00, now 15:00 -> 1h old
    assert slip.status == "rejected"
    assert _legs(slip.id, session)[0].reason == "stale_odds"
