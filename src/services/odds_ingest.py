"""Gated ingestion of OCR-extracted odds: stage -> validate -> promote.

An external step (e.g. Codex reading bookmaker screenshots) emits *captures*.
Each capture is one bookmaker's reading of one market for one match, with its
selections. We:

1. **stage** every selection into ``odds_ingest_raw`` with provenance;
2. **validate** each capture (team resolves? timestamp before kickoff? odds
   plausible? market complete? overround sane? not an outlier vs other books?);
3. **promote** only validated rows into ``odds_snapshots`` / ``current_odds``.

Rejected captures stay in staging with a reason, so nothing wrong reaches the
model or a bet slip, and every decision is auditable.

Capture payload::

    {"batch_id": "...",
     "captures": [
       {"screenshot_id", "source_url"?, "bookmaker", "home", "away",
        "league", "season", "kickoff"?, "captured_at", "market", "line"?,
        "ocr_confidence"?,
        "selections": [{"selection", "odd", "ocr_confidence"?}, ...]}]}
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Match, OddsIngestRaw
from ..transformers import OddsDTO
from ..transformers.base import parse_datetime
from . import betting_repository as br
from . import football_repository as fb_repo
from . import reference_service as ref

# --- tunable validation thresholds -----------------------------------------
ODD_MIN = 1.01
ODD_MAX = 1000.0
OVERROUND_MIN = -0.02       # below 0 ~ arbitrage -> likely a misread
OVERROUND_MAX = 0.25        # absurd margin -> likely a misread
OUTLIER_ABS = 0.08          # implied-prob deviation from cross-book median
MIN_BOOKS_FOR_CONSENSUS = 3

REQUIRED_SELECTIONS = {
    "1x2": {"home", "draw", "away"},
    "btts": {"yes", "no"},
    "ou": {"over", "under"},
    "ah": {"home", "away"},
}
OVERROUND_MARKETS = set(REQUIRED_SELECTIONS)


def _norm_sel(value: str) -> str:
    return str(value).strip().lower()


def _resolve_match_strict(
    session: Session, home, away, league, season, kickoff
) -> Optional[int]:
    """Resolve to a match id ONLY if both team names map to known teams.

    Never creates a team from an OCR name (a misread must not invent an entity).
    """
    if not (home and away and league and season):
        return None
    sport = ref.get_or_create_sport(session, "Football")
    home_team = fb_repo.find_team(session, sport, home)
    away_team = fb_repo.find_team(session, sport, away)
    if home_team is None or away_team is None:
        return None
    source = ref.get_or_create_source(session, "manual")
    competition = ref.get_or_create_competition(session, sport, source, league)
    season_obj = ref.get_or_create_season(session, competition, str(season))
    match = session.scalar(
        select(Match).where(
            Match.season_id == season_obj.id,
            Match.home_team_id == home_team.id,
            Match.away_team_id == away_team.id,
        )
    )
    if match is None:
        match = Match(
            competition_id=competition.id, season_id=season_obj.id,
            source_id=source.id, home_team_id=home_team.id,
            away_team_id=away_team.id, match_datetime=kickoff,
        )
        session.add(match)
        session.flush()
    return match.id


def _validate_capture(
    rows: list[OddsIngestRaw], market: str, match_id: Optional[int],
    min_confidence: float,
) -> Optional[str]:
    """Return a rejection reason, or None if the capture passes."""
    if match_id is None:
        return "unresolved_team"
    for r in rows:
        if r.captured_at is None:
            return "no_timestamp"
        if r.kickoff is not None and r.captured_at > r.kickoff:
            return "after_kickoff"
        if r.odd < ODD_MIN or r.odd > ODD_MAX:
            return "implausible_odd"
        if min_confidence and r.ocr_confidence is not None and r.ocr_confidence < min_confidence:
            return "low_confidence"
    required = REQUIRED_SELECTIONS.get(market)
    if required and {r.selection for r in rows} != required:
        return "incomplete_market"
    if market in OVERROUND_MARKETS:
        overround = sum(1.0 / r.odd for r in rows) - 1.0
        if overround < OVERROUND_MIN or overround > OVERROUND_MAX:
            return "bad_overround"
    return None


def _flag_outliers(validated_rows: list[OddsIngestRaw]) -> None:
    """Reject prices that disagree wildly with the cross-bookmaker consensus."""
    groups: dict[tuple, list[OddsIngestRaw]] = defaultdict(list)
    for r in validated_rows:
        groups[(r.match_id, r.market, r.selection, r.line)].append(r)
    for rows in groups.values():
        by_book = {r.bookmaker: r for r in rows}
        if len(by_book) < MIN_BOOKS_FOR_CONSENSUS:
            continue
        implied = {bk: 1.0 / r.odd for bk, r in by_book.items()}
        median = statistics.median(implied.values())
        for bk, r in by_book.items():
            if abs(implied[bk] - median) > OUTLIER_ABS:
                r.status = "rejected"
                r.reject_reason = "outlier_vs_consensus"


def ingest_capture(
    session: Session, payload: dict[str, Any], min_confidence: float = 0.0,
    promote: bool = True,
) -> dict[str, Any]:
    """Stage, validate and (optionally) promote a capture payload.

    Returns a report with counts and rejections-by-reason.
    """
    batch_id = payload.get("batch_id")
    captures = payload.get("captures", []) or []
    all_rows: list[OddsIngestRaw] = []

    for cap in captures:
        market = cap["market"]
        line = cap.get("line")
        rows: list[OddsIngestRaw] = []
        for sel in cap.get("selections", []):
            row = OddsIngestRaw(
                batch_id=batch_id,
                screenshot_id=cap.get("screenshot_id"),
                source_url=cap.get("source_url"),
                ocr_confidence=sel.get("ocr_confidence", cap.get("ocr_confidence")),
                bookmaker=cap["bookmaker"],
                home_raw=cap.get("home"), away_raw=cap.get("away"),
                league=cap.get("league"),
                season=str(cap["season"]) if cap.get("season") is not None else None,
                market=market, selection=_norm_sel(sel["selection"]),
                line=line, odd=float(sel["odd"]),
                captured_at=parse_datetime(cap.get("captured_at")),
                kickoff=parse_datetime(cap.get("kickoff")),
                status="pending",
            )
            session.add(row)
            rows.append(row)
        session.flush()

        match_id = _resolve_match_strict(
            session, cap.get("home"), cap.get("away"), cap.get("league"),
            cap.get("season"), parse_datetime(cap.get("kickoff")),
        )
        reason = _validate_capture(rows, market, match_id, min_confidence)
        for row in rows:
            row.match_id = match_id
            row.status = "rejected" if reason else "validated"
            row.reject_reason = reason
        all_rows.extend(rows)
    session.flush()

    _flag_outliers([r for r in all_rows if r.status == "validated"])
    session.flush()

    if promote:
        for row in all_rows:
            if row.status != "validated":
                continue
            snap = br.record_odds(session, row.match_id, OddsDTO(
                bookmaker=row.bookmaker, market=row.market, selection=row.selection,
                odd=row.odd, line=row.line, captured_at=row.captured_at,
                source_url=row.source_url,
            ))
            row.promoted_snapshot_id = snap.id
            row.status = "promoted"
        session.flush()

    return _report(all_rows, len(captures))


def _report(rows: list[OddsIngestRaw], n_captures: int) -> dict[str, Any]:
    by_reason: dict[str, int] = defaultdict(int)
    counts = {"promoted": 0, "validated": 0, "rejected": 0}
    for r in rows:
        if r.status == "rejected":
            counts["rejected"] += 1
            by_reason[r.reject_reason or "unknown"] += 1
        elif r.status == "promoted":
            counts["promoted"] += 1
        elif r.status == "validated":
            counts["validated"] += 1
    return {
        "captures": n_captures,
        "staged": len(rows),
        "promoted": counts["promoted"],
        "validated_not_promoted": counts["validated"],
        "rejected": counts["rejected"],
        "rejected_by_reason": dict(by_reason),
    }
