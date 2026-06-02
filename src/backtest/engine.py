"""Value-betting backtest over stored ``predictions`` x ``odds`` x results.

For every stored prediction we look up a real price (best available, or the
closing line), compute edge ``EV = p * odd - 1`` and, if it clears the
threshold and passes the filters, simulate a flat-stake bet settled from
``market_results``. Output is a per-bet ledger + a summary (ROI, yield, hit
rate, drawdown), sliceable by league / market / odd bucket.

This never reads ``matches.forecast_*`` and only consumes pre-computed
predictions, so there is no look-ahead by construction (provided the predictions
themselves are leakage-free — see ``src/features``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    BetDecision,
    Competition,
    CurrentOdds,
    Market,
    MarketResult,
    Match,
    OddsSnapshot,
    Prediction,
    Season,
    Team,
)

ODD_BUCKETS = [1.0, 1.5, 2.0, 3.0, 5.0, 10.0, float("inf")]


@dataclass
class BacktestConfig:
    model_name: str
    model_version: Optional[str] = None
    league: Optional[str] = None        # competition code filter
    threshold: float = 0.0              # minimum EV to place a bet
    stake: float = 1.0
    price: str = "best"                # "best" (max book) | "closing"
    min_prob: float = 0.0
    odd_min: Optional[float] = None
    odd_max: Optional[float] = None
    run_label: str = "backtest"

    def as_filters(self) -> dict:
        return {
            "threshold": self.threshold, "price": self.price,
            "min_prob": self.min_prob, "odd_min": self.odd_min,
            "odd_max": self.odd_max, "league": self.league,
        }


@dataclass
class BacktestResult:
    config: BacktestConfig
    bets: pd.DataFrame
    decisions: pd.DataFrame
    summary: dict = field(default_factory=dict)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _odd_for(
    session: Session, pred: Prediction, price: str
) -> Optional[float]:
    line_pred = (
        OddsSnapshot.line.is_(None) if pred.line is None else OddsSnapshot.line == pred.line
    )
    if price == "closing":
        return session.scalar(
            select(func.max(OddsSnapshot.odd)).where(
                OddsSnapshot.match_id == pred.match_id,
                OddsSnapshot.market_id == pred.market_id,
                OddsSnapshot.selection == pred.selection,
                OddsSnapshot.is_closing.is_(True),
                line_pred,
            )
        )
    line_cur = (
        CurrentOdds.line.is_(None) if pred.line is None else CurrentOdds.line == pred.line
    )
    return session.scalar(
        select(func.max(CurrentOdds.odd)).where(
            CurrentOdds.match_id == pred.match_id,
            CurrentOdds.market_id == pred.market_id,
            CurrentOdds.selection == pred.selection,
            line_cur,
        )
    )


def _result_for(session: Session, pred: Prediction) -> Optional[str]:
    line_r = (
        MarketResult.line.is_(None) if pred.line is None else MarketResult.line == pred.line
    )
    return session.scalar(
        select(MarketResult.outcome).where(
            MarketResult.match_id == pred.match_id,
            MarketResult.market_id == pred.market_id,
            MarketResult.selection == pred.selection,
            line_r,
        )
    )


def _pnl(outcome: str, odd: float, stake: float) -> float:
    if outcome == "won":
        return stake * (odd - 1.0)
    if outcome == "lost":
        return -stake
    return 0.0  # push / void


def run_backtest(
    session: Session, config: BacktestConfig, persist_decisions: bool = False
) -> BacktestResult:
    stmt = select(Prediction).where(Prediction.model_name == config.model_name)
    if config.model_version is not None:
        stmt = stmt.where(Prediction.model_version == config.model_version)
    preds = session.scalars(stmt).all()

    bet_rows: list[dict] = []
    dec_rows: list[dict] = []

    for pred in preds:
        match = session.get(Match, pred.match_id)
        comp = session.get(Competition, match.competition_id) if match else None
        if config.league and (comp is None or comp.code != config.league):
            continue
        market = session.get(Market, pred.market_id)
        league = comp.code if comp else None

        odd = _odd_for(session, pred, config.price)
        ev = (pred.probability * odd - 1.0) if odd else None

        decided, reason, outcome, pnl = False, None, None, None
        if odd is None:
            reason = "no_odds"
        elif pred.probability < config.min_prob:
            reason = "prob_below_min"
        elif config.odd_min is not None and odd < config.odd_min:
            reason = "odd_below_min"
        elif config.odd_max is not None and odd > config.odd_max:
            reason = "odd_above_max"
        elif ev is None or ev <= config.threshold:
            reason = "ev_below_threshold"
        else:
            outcome = _result_for(session, pred)
            if outcome is None:
                reason = "no_result"
            else:
                decided, reason = True, "value_bet"
                pnl = _pnl(outcome, odd, config.stake)
                bet_rows.append({
                    "match_id": pred.match_id, "league": league,
                    "market": market.code if market else None,
                    "selection": pred.selection, "line": pred.line,
                    "prob": pred.probability, "odd": odd, "ev": round(ev, 4),
                    "outcome": outcome, "stake": config.stake,
                    "pnl": round(pnl, 4),
                })

        dec_rows.append({
            "match_id": pred.match_id, "league": league,
            "market": market.code if market else None,
            "selection": pred.selection, "prob": pred.probability,
            "odd": odd, "ev": round(ev, 4) if ev is not None else None,
            "decided": decided, "reason": reason, "outcome": outcome, "pnl": pnl,
        })
        if persist_decisions:
            session.add(BetDecision(
                run_label=config.run_label, match_id=pred.match_id,
                market_id=pred.market_id, selection=pred.selection, line=pred.line,
                model_name=pred.model_name, model_version=pred.model_version,
                probability=pred.probability, odd=odd,
                ev=round(ev, 4) if ev is not None else None,
                decided=decided, reason=reason, outcome=outcome, pnl=pnl,
                filters=config.as_filters(),
            ))

    if persist_decisions:
        session.flush()

    bets = pd.DataFrame(bet_rows)
    decisions = pd.DataFrame(dec_rows)
    return BacktestResult(
        config=config, bets=bets, decisions=decisions,
        summary=_summary(bets),
    )


def _summary(bets: pd.DataFrame) -> dict:
    n = len(bets)
    if n == 0:
        return {"bets": 0, "staked": 0.0, "profit": 0.0, "roi_pct": None,
                "hit_rate_pct": None, "max_drawdown": 0.0}
    staked = float(bets["stake"].sum())
    profit = float(bets["pnl"].sum())
    wins = int((bets["outcome"] == "won").sum())
    equity = bets["pnl"].cumsum()
    drawdown = float((equity.cummax() - equity).max())
    return {
        "bets": n,
        "staked": round(staked, 2),
        "profit": round(profit, 2),
        "roi_pct": round(100 * profit / staked, 2) if staked else None,
        "hit_rate_pct": round(100 * wins / n, 1),
        "max_drawdown": round(drawdown, 2),
    }


def summarize_by(bets: pd.DataFrame, dimension: str) -> pd.DataFrame:
    """Slice a bet ledger by 'league', 'market' or 'odd_bucket'."""
    if bets.empty:
        return pd.DataFrame(columns=[dimension, "bets", "staked", "profit",
                                     "roi_pct", "hit_rate_pct"])
    df = bets.copy()
    if dimension == "odd_bucket":
        df["odd_bucket"] = pd.cut(df["odd"], ODD_BUCKETS, right=False)
    grouped = df.groupby(dimension, observed=True).apply(
        lambda g: pd.Series({
            "bets": len(g),
            "staked": round(g["stake"].sum(), 2),
            "profit": round(g["pnl"].sum(), 2),
            "roi_pct": round(100 * g["pnl"].sum() / g["stake"].sum(), 2)
            if g["stake"].sum() else None,
            "hit_rate_pct": round(100 * (g["outcome"] == "won").mean(), 1),
        }),
        include_groups=False,
    )
    return grouped.reset_index()
