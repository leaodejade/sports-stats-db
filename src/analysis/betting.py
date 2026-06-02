"""Read-only analytics over the betting data layer (returns pandas DataFrames).

Covers the metrics the audit flagged as missing: implied probability / overround,
best price per market, Closing Line Value (CLV), and bankroll P&L (ROI, hit rate,
drawdown). Pure reads — never mutates the database.

NOTE: nothing here promotes a real-money bet. These are evaluation metrics over
*simulated* bets and *stored* odds.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    BankrollTransaction,
    Bookmaker,
    CurrentOdds,
    Market,
    OddsSnapshot,
    SimulatedBet,
)


def _df(rows, columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


# ---------------------------------------------------------------------------
# Odds: implied probability, overround, best price, movement
# ---------------------------------------------------------------------------
def implied_probability(odd: float) -> Optional[float]:
    return 1.0 / odd if odd and odd > 0 else None


def market_overround(
    session: Session, match_id: int, bookmaker: str, market: str
) -> Optional[float]:
    """Bookmaker margin for one market = sum(1/odd) - 1 (e.g. 0.05 = 5%)."""
    stmt = (
        select(CurrentOdds.odd)
        .join(Bookmaker, Bookmaker.id == CurrentOdds.bookmaker_id)
        .join(Market, Market.id == CurrentOdds.market_id)
        .where(
            CurrentOdds.match_id == match_id,
            Bookmaker.name == bookmaker,
            Market.code == market,
        )
    )
    odds = [o for (o,) in session.execute(stmt).all() if o]
    if not odds:
        return None
    return round(sum(1.0 / o for o in odds) - 1.0, 4)


def best_odds(session: Session, match_id: Optional[int] = None) -> pd.DataFrame:
    """Best (highest) available price per match/market/selection/line."""
    stmt = (
        select(
            CurrentOdds.match_id, Market.code, CurrentOdds.selection,
            CurrentOdds.line, CurrentOdds.odd, Bookmaker.name,
        )
        .join(Market, Market.id == CurrentOdds.market_id)
        .join(Bookmaker, Bookmaker.id == CurrentOdds.bookmaker_id)
    )
    if match_id is not None:
        stmt = stmt.where(CurrentOdds.match_id == match_id)
    df = _df(
        session.execute(stmt).all(),
        ["match_id", "market", "selection", "line", "odd", "bookmaker"],
    )
    if df.empty:
        return df
    idx = df.groupby(["match_id", "market", "selection", "line"], dropna=False)["odd"].idxmax()
    best = df.loc[idx].reset_index(drop=True)
    best["implied_prob"] = (1.0 / best["odd"]).round(4)
    return best


def odds_movement(
    session: Session, match_id: int, market: str, selection: str,
    line: Optional[float] = None,
) -> pd.DataFrame:
    """Full captured price history for one selection, oldest first."""
    stmt = (
        select(
            OddsSnapshot.captured_at, Bookmaker.name, OddsSnapshot.odd,
            OddsSnapshot.is_opening, OddsSnapshot.is_closing,
        )
        .join(Market, Market.id == OddsSnapshot.market_id)
        .join(Bookmaker, Bookmaker.id == OddsSnapshot.bookmaker_id)
        .where(
            OddsSnapshot.match_id == match_id,
            Market.code == market,
            OddsSnapshot.selection == selection,
        )
        .order_by(OddsSnapshot.captured_at.asc())
    )
    if line is not None:
        stmt = stmt.where(OddsSnapshot.line == line)
    return _df(
        session.execute(stmt).all(),
        ["captured_at", "bookmaker", "odd", "is_opening", "is_closing"],
    )


# ---------------------------------------------------------------------------
# Closing Line Value
# ---------------------------------------------------------------------------
def clv_report(session: Session) -> pd.DataFrame:
    """Per-bet CLV: did we beat the closing line?

    CLV% = odd_taken / closing_odd - 1 (positive means we got a better price
    than the eventual close — the strongest evidence of genuine edge).
    """
    bets = session.scalars(select(SimulatedBet)).all()
    rows = []
    for bet in bets:
        closing = session.scalar(
            select(OddsSnapshot.odd)
            .where(
                OddsSnapshot.match_id == bet.match_id,
                OddsSnapshot.market_id == bet.market_id,
                OddsSnapshot.selection == bet.selection,
                OddsSnapshot.is_closing.is_(True),
                (OddsSnapshot.line.is_(None) if bet.line is None
                 else OddsSnapshot.line == bet.line),
            )
            .order_by(OddsSnapshot.odd.desc())
        )
        clv = (bet.odd_taken / closing - 1.0) if closing else None
        rows.append((bet.id, bet.match_id, bet.selection, bet.odd_taken,
                     closing, round(clv, 4) if clv is not None else None))
    df = _df(rows, ["bet_id", "match_id", "selection", "odd_taken",
                    "closing_odd", "clv"])
    return df


def clv_summary(session: Session) -> dict:
    df = clv_report(session)
    valid = df.dropna(subset=["clv"])
    if valid.empty:
        return {"bets_with_closing": 0, "mean_clv": None, "pct_positive": None}
    return {
        "bets_with_closing": int(len(valid)),
        "mean_clv": round(float(valid["clv"].mean()), 4),
        "pct_positive": round(float((valid["clv"] > 0).mean() * 100), 1),
    }


# ---------------------------------------------------------------------------
# Bankroll P&L
# ---------------------------------------------------------------------------
def bankroll_curve(session: Session) -> pd.DataFrame:
    stmt = select(
        BankrollTransaction.ts, BankrollTransaction.kind,
        BankrollTransaction.amount, BankrollTransaction.balance_after,
    ).order_by(BankrollTransaction.id.asc())
    return _df(session.execute(stmt).all(), ["ts", "kind", "amount", "balance"])


def pnl_summary(session: Session) -> dict:
    """Aggregate performance over *settled* simulated bets."""
    bets = session.scalars(
        select(SimulatedBet).where(SimulatedBet.status != "pending")
    ).all()
    settled = [b for b in bets if b.pnl is not None]
    n = len(settled)
    if n == 0:
        return {"bets": 0, "staked": 0.0, "profit": 0.0, "roi_pct": None,
                "hit_rate_pct": None, "max_drawdown": 0.0}

    staked = sum(b.stake for b in settled)
    profit = sum(b.pnl for b in settled)
    wins = sum(1 for b in settled if b.pnl > 0)

    # Max drawdown from the bankroll curve.
    curve = bankroll_curve(session)
    max_dd = 0.0
    if not curve.empty:
        bal = curve["balance"].astype(float)
        running_peak = bal.cummax()
        max_dd = float((running_peak - bal).max())

    return {
        "bets": n,
        "staked": round(staked, 2),
        "profit": round(profit, 2),
        "roi_pct": round(100 * profit / staked, 2) if staked else None,
        "hit_rate_pct": round(100 * wins / n, 1),
        "max_drawdown": round(max_dd, 2),
    }
