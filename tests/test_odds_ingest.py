"""Tests for the gated OCR-odds ingestion (audit phase B / trust gate)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.models import CurrentOdds, OddsIngestRaw, OddsSnapshot, Team
from src.services import betting_repository as br
from src.services import odds_ingest as oi


@pytest.fixture()
def known_teams(session):
    """Seed the canonical teams so OCR names can resolve (the safety rule)."""
    br.resolve_match(session, "Arsenal", "Chelsea", "EPL", "2023")
    br.resolve_match(session, "Liverpool", "Everton", "EPL", "2023")
    return session


def _capture(bookmaker, home, away, market, selections, **kw):
    cap = {"bookmaker": bookmaker, "home": home, "away": away,
           "league": "EPL", "season": "2023",
           "captured_at": "2023-10-08 15:55:00", "kickoff": "2023-10-08 16:30:00",
           "market": market, "selections": selections}
    cap.update(kw)
    return cap


def test_valid_capture_is_promoted(known_teams):
    session = known_teams
    payload = {"batch_id": "b1", "captures": [
        _capture("Pinnacle", "Arsenal", "Chelsea", "1x2", [
            {"selection": "home", "odd": 2.10},
            {"selection": "draw", "odd": 3.40},
            {"selection": "away", "odd": 3.60},
        ])
    ]}
    report = oi.ingest_capture(session, payload)
    assert report["promoted"] == 3 and report["rejected"] == 0
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 3
    assert session.scalar(select(func.count()).select_from(CurrentOdds)) == 3
    # staging rows kept for audit, marked promoted
    assert session.scalar(
        select(func.count()).select_from(OddsIngestRaw)
        .where(OddsIngestRaw.status == "promoted")
    ) == 3


def test_unresolved_team_is_quarantined_not_created(known_teams):
    session = known_teams
    before = session.scalar(select(func.count()).select_from(Team))
    payload = {"captures": [
        _capture("Bet365", "Arsenull FC", "Chelsea", "1x2", [
            {"selection": "home", "odd": 2.1}, {"selection": "draw", "odd": 3.4},
            {"selection": "away", "odd": 3.6}])
    ]}
    report = oi.ingest_capture(session, payload)
    assert report["rejected"] == 3
    assert report["rejected_by_reason"]["unresolved_team"] == 3
    # No phantom team created, nothing promoted.
    assert session.scalar(select(func.count()).select_from(Team)) == before
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 0


def test_implausible_odd_rejected(known_teams):
    session = known_teams
    # 2.10 misread as 21.0 (decimal point) -> bad overround catches it.
    payload = {"captures": [
        _capture("Bet365", "Arsenal", "Chelsea", "1x2", [
            {"selection": "home", "odd": 21.0},
            {"selection": "draw", "odd": 3.40},
            {"selection": "away", "odd": 3.60}])
    ]}
    report = oi.ingest_capture(session, payload)
    assert report["promoted"] == 0
    assert report["rejected_by_reason"].get("bad_overround") == 3


def test_incomplete_market_rejected(known_teams):
    session = known_teams
    payload = {"captures": [
        _capture("Bet365", "Arsenal", "Chelsea", "1x2", [
            {"selection": "home", "odd": 2.10},
            {"selection": "away", "odd": 3.60}])  # missing draw
    ]}
    report = oi.ingest_capture(session, payload)
    assert report["rejected_by_reason"].get("incomplete_market") == 2


def test_after_kickoff_rejected(known_teams):
    session = known_teams
    payload = {"captures": [
        _capture("Bet365", "Arsenal", "Chelsea", "1x2", [
            {"selection": "home", "odd": 2.10}, {"selection": "draw", "odd": 3.40},
            {"selection": "away", "odd": 3.60}],
            captured_at="2023-10-08 18:00:00")  # after the 16:30 kickoff
    ]}
    report = oi.ingest_capture(session, payload)
    assert report["rejected_by_reason"].get("after_kickoff") == 3


def test_cross_book_outlier_rejected(known_teams):
    session = known_teams
    # Three books; Bet365's home price disagrees with consensus but its market
    # still has a sane overround (so only the consensus check can catch it).
    sels_ok = [{"selection": "home", "odd": 2.10}, {"selection": "draw", "odd": 3.40},
               {"selection": "away", "odd": 3.60}]
    sels_bad = [{"selection": "home", "odd": 1.70}, {"selection": "draw", "odd": 3.40},
                {"selection": "away", "odd": 3.60}]
    payload = {"captures": [
        _capture("Pinnacle", "Arsenal", "Chelsea", "1x2", sels_ok),
        _capture("Betano", "Arsenal", "Chelsea", "1x2", sels_ok),
        _capture("Bet365", "Arsenal", "Chelsea", "1x2", sels_bad),
    ]}
    report = oi.ingest_capture(session, payload)
    assert report["rejected_by_reason"].get("outlier_vs_consensus") == 1
    # the outlier 'home' is rejected; the other 8 selections promote
    assert report["promoted"] == 8


def test_no_promote_only_stages(known_teams):
    session = known_teams
    payload = {"captures": [
        _capture("Pinnacle", "Arsenal", "Chelsea", "1x2", [
            {"selection": "home", "odd": 2.10}, {"selection": "draw", "odd": 3.40},
            {"selection": "away", "odd": 3.60}])
    ]}
    report = oi.ingest_capture(session, payload, promote=False)
    assert report["validated_not_promoted"] == 3 and report["promoted"] == 0
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 0
