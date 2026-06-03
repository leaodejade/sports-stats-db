"""Odds maths: implied probability, bookmaker margin (overround) and de-vig.

Raw ``1/odd`` includes the bookmaker margin, so it overstates probabilities and
is not comparable to a model's. De-vigging removes the margin (here by simple
proportional normalisation) to get fair, comparable probabilities — the honest
basis for edge and CLV.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Bookmaker, CurrentOdds, Market


def implied_probability(odd: Optional[float]) -> Optional[float]:
    """Raw implied probability ``1/odd`` (still includes the margin)."""
    return 1.0 / odd if odd and odd > 0 else None


def overround(odds: dict[str, float]) -> Optional[float]:
    """Bookmaker margin of a market = sum(1/odd) - 1 (e.g. 0.05 = 5%)."""
    inv = [1.0 / o for o in odds.values() if o and o > 0]
    return sum(inv) - 1.0 if inv else None


def no_vig_probabilities(odds: dict[str, float]) -> dict[str, float]:
    """Fair (de-vigged) probabilities by proportional normalisation.

    ``{"home": 2.0, "draw": 3.5, "away": 4.0}`` -> probabilities summing to 1.
    """
    inv = {k: 1.0 / v for k, v in odds.items() if v and v > 0}
    total = sum(inv.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in inv.items()}


def fair_odds(probability: Optional[float]) -> Optional[float]:
    return 1.0 / probability if probability and probability > 0 else None


def market_no_vig(
    session: Session, match_id: int, market_code: str, bookmaker: str,
    line: Optional[float] = None,
) -> dict[str, float]:
    """De-vigged probabilities for one bookmaker's market, from current odds."""
    line_eq = CurrentOdds.line.is_(None) if line is None else CurrentOdds.line == line
    rows = session.execute(
        select(CurrentOdds.selection, CurrentOdds.odd)
        .join(Market, Market.id == CurrentOdds.market_id)
        .join(Bookmaker, Bookmaker.id == CurrentOdds.bookmaker_id)
        .where(
            CurrentOdds.match_id == match_id,
            Market.code == market_code,
            Bookmaker.name == bookmaker,
            line_eq,
        )
    ).all()
    return no_vig_probabilities({sel: odd for sel, odd in rows})
