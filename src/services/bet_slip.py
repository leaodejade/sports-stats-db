"""Build a bet slip (bilhete) behind a pre-flight gate.

Before a slip is marked ``ready``, EVERY leg must pass checks designed to stop a
wrong ticket from being emitted:

* the odds exist and (optionally) came through the OCR validation gate
  (a ``promoted`` ``odds_ingest_raw`` row) — i.e. not raw/unvetted numbers;
* the market is complete (all required selections priced);
* the price is fresh and dated before kickoff (no stale / in-play odds);
* (optional) a model prediction exists with at least ``min_edge`` of value.

A multi (accumulator) is refused whole if any leg fails; every rejection is
recorded in ``bet_decisions`` for audit. Nothing here places a real-money bet.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    BetDecision,
    BetSlip,
    BetSlipLeg,
    CurrentOdds,
    Market,
    Match,
    OddsIngestRaw,
    Prediction,
)
from .odds_ingest import REQUIRED_SELECTIONS


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _line_eq(column, line: Optional[float]):
    return column.is_(None) if line is None else column == line


def _best_current(
    session: Session, match_id: int, market_id: int, selection: str, line: Optional[float]
):
    """Best (highest) current price for a selection, with its capture time."""
    return session.execute(
        select(CurrentOdds.odd, CurrentOdds.captured_at)
        .where(
            CurrentOdds.match_id == match_id,
            CurrentOdds.market_id == market_id,
            CurrentOdds.selection == selection,
            _line_eq(CurrentOdds.line, line),
        )
        .order_by(CurrentOdds.odd.desc())
    ).first()


def _market_complete(
    session: Session, match_id: int, market_code: str, market_id: int, line: Optional[float]
) -> bool:
    required = REQUIRED_SELECTIONS.get(market_code)
    if not required:
        return True
    have = set(session.scalars(
        select(CurrentOdds.selection).where(
            CurrentOdds.match_id == match_id,
            CurrentOdds.market_id == market_id,
            _line_eq(CurrentOdds.line, line),
        )
    ).all())
    return required.issubset(have)


def _is_gated(
    session: Session, match_id: int, market_id: int, selection: str, line: Optional[float]
) -> bool:
    """True if this selection has a promoted (gate-validated) staging row."""
    n = session.scalar(
        select(func.count()).select_from(OddsIngestRaw).where(
            OddsIngestRaw.match_id == match_id,
            OddsIngestRaw.market == _market_code(session, market_id),
            OddsIngestRaw.selection == selection,
            _line_eq(OddsIngestRaw.line, line),
            OddsIngestRaw.status == "promoted",
        )
    )
    return bool(n)


def _market_code(session: Session, market_id: int) -> str:
    m = session.get(Market, market_id)
    return m.code if m else ""


def _prediction_prob(
    session: Session, match_id: int, market_id: int, selection: str,
    line: Optional[float], model_name: Optional[str], model_version: Optional[str],
) -> Optional[float]:
    if not model_name:
        return None
    stmt = select(Prediction.probability).where(
        Prediction.match_id == match_id,
        Prediction.market_id == market_id,
        Prediction.selection == selection,
        _line_eq(Prediction.line, line),
        Prediction.model_name == model_name,
    )
    if model_version:
        stmt = stmt.where(Prediction.model_version == model_version)
    return session.scalar(stmt)


def _validate_leg(
    session: Session, spec: dict, *, require_gate: bool, freshness_seconds: Optional[int],
    min_edge: Optional[float], model_name: Optional[str], model_version: Optional[str],
    now: datetime,
) -> dict[str, Any]:
    """Return a dict with resolved odd/prob/market_id and a rejection reason."""
    match_id = spec["match_id"]
    selection = str(spec["selection"]).strip().lower()
    line = spec.get("line")
    market_code = spec["market"]

    out: dict[str, Any] = {
        "match_id": match_id, "selection": selection, "line": line,
        "market_id": None, "odd": None, "prob": None, "reason": None,
    }
    market = session.scalar(select(Market).where(Market.code == market_code))
    if market is None:
        out["reason"] = "no_market"
        return out
    out["market_id"] = market.id

    row = _best_current(session, match_id, market.id, selection, line)
    if row is None:
        out["reason"] = "no_odds"
        return out
    odd, captured_at = row[0], row[1]
    out["odd"] = odd

    if require_gate and not _is_gated(session, match_id, market.id, selection, line):
        out["reason"] = "unvalidated_odds"
        return out
    if not _market_complete(session, match_id, market_code, market.id, line):
        out["reason"] = "incomplete_market"
        return out

    match = session.get(Match, match_id)
    kickoff = match.match_datetime if match else None
    if kickoff is not None and now > kickoff:
        out["reason"] = "after_kickoff"
        return out
    if kickoff is not None and captured_at is not None and captured_at > kickoff:
        out["reason"] = "stale_after_kickoff"
        return out
    if freshness_seconds is not None and captured_at is not None:
        age = (now - captured_at).total_seconds()
        if age > freshness_seconds:
            out["reason"] = "stale_odds"
            return out

    prob = _prediction_prob(
        session, match_id, market.id, selection, line, model_name, model_version
    )
    out["prob"] = prob
    if min_edge is not None and model_name:
        if prob is None:
            out["reason"] = "no_prediction"
            return out
        if prob * odd - 1.0 < min_edge:
            out["reason"] = "below_min_edge"
            return out
    return out


def build_bet_slip(
    session: Session,
    legs: list[dict],
    stake: float = 0.0,
    kind: str = "multi",
    label: str = "slip",
    model_name: Optional[str] = None,
    model_version: Optional[str] = None,
    require_gate: bool = True,
    freshness_seconds: Optional[int] = None,
    min_edge: Optional[float] = None,
    now: Optional[datetime] = None,
) -> BetSlip:
    """Assemble a slip behind the pre-flight gate; ``ready`` only if all legs pass."""
    now = now or _utcnow()
    slip = BetSlip(label=label, kind=kind, stake=stake, status="draft",
                   model_name=model_name, model_version=model_version)
    session.add(slip)
    session.flush()

    all_ok = True
    combined_odd = 1.0
    combined_prob = 1.0
    have_probs = True

    for spec in legs:
        v = _validate_leg(
            session, spec, require_gate=require_gate,
            freshness_seconds=freshness_seconds, min_edge=min_edge,
            model_name=model_name, model_version=model_version, now=now,
        )
        ok = v["reason"] is None
        session.add(BetSlipLeg(
            slip_id=slip.id, match_id=v["match_id"], market_id=v["market_id"],
            selection=v["selection"], line=v["line"], odd=v["odd"],
            probability=v["prob"], status="ok" if ok else "rejected",
            reason=v["reason"],
        ))
        if ok:
            combined_odd *= v["odd"]
            if v["prob"] is not None:
                combined_prob *= v["prob"]
            else:
                have_probs = False
        else:
            all_ok = False
            session.add(BetDecision(
                run_label=f"slip:{slip.id}", match_id=v["match_id"],
                market_id=v["market_id"] or 0, selection=v["selection"], line=v["line"],
                model_name=model_name, model_version=model_version,
                probability=v["prob"], odd=v["odd"], ev=None,
                decided=False, reason=v["reason"],
            ))

    if all_ok and legs:
        slip.combined_odd = round(combined_odd, 4)
        slip.status = "ready"
        if model_name and have_probs:
            slip.ev = round(combined_prob * combined_odd - 1.0, 4)
    else:
        slip.status = "rejected"
        slip.reject_reason = "leg_failed_preflight"
    session.flush()
    return slip
