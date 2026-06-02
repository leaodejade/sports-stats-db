"""Probability calibration of stored model predictions vs realised outcomes.

Joins ``predictions`` to ``market_results`` to get a binary target (won = 1,
lost = 0; push/void excluded) and reports calibration quality: a reliability
table plus Brier score and log-loss. Sliceable by league / market / odd bucket.

Lower Brier and lower log-loss are better; a well-calibrated model has predicted
≈ realised in every probability bin.
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Competition,
    CurrentOdds,
    Market,
    MarketResult,
    Match,
    Prediction,
)

_PROB_BINS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
_ODD_BUCKETS = [1.0, 1.5, 2.0, 3.0, 5.0, 10.0, float("inf")]


def prediction_outcomes(
    session: Session,
    model_name: str,
    model_version: Optional[str] = None,
    market: Optional[str] = None,
) -> pd.DataFrame:
    """One row per (prediction with a settled result): prob, won(0/1), league, odd."""
    stmt = (
        select(
            Prediction.match_id, Prediction.probability, Competition.code,
            Market.code, Prediction.selection, MarketResult.outcome,
        )
        .join(Market, Market.id == Prediction.market_id)
        .join(Match, Match.id == Prediction.match_id)
        .join(Competition, Competition.id == Match.competition_id)
        .join(
            MarketResult,
            (MarketResult.match_id == Prediction.match_id)
            & (MarketResult.market_id == Prediction.market_id)
            & (MarketResult.selection == Prediction.selection),
        )
        .where(Prediction.model_name == model_name)
    )
    if model_version is not None:
        stmt = stmt.where(Prediction.model_version == model_version)
    if market is not None:
        stmt = stmt.where(Market.code == market)

    df = pd.DataFrame(
        session.execute(stmt).all(),
        columns=["match_id", "prob", "league", "market", "selection", "outcome"],
    )
    if df.empty:
        return df
    df = df[df["outcome"].isin(["won", "lost"])].copy()
    df["won"] = (df["outcome"] == "won").astype(int)
    return df


def brier_score(df: pd.DataFrame) -> Optional[float]:
    if df.empty:
        return None
    return round(float(((df["prob"] - df["won"]) ** 2).mean()), 4)


def log_loss(df: pd.DataFrame) -> Optional[float]:
    if df.empty:
        return None
    p = df["prob"].clip(1e-9, 1 - 1e-9)
    ll = -(df["won"] * p.apply(math.log) + (1 - df["won"]) * (1 - p).apply(math.log))
    return round(float(ll.mean()), 4)


def calibration_table(df: pd.DataFrame) -> pd.DataFrame:
    """Reliability table: per probability bin, predicted vs realised win rate."""
    cols = ["bin", "n", "pred_mean", "real_rate"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    d = df.copy()
    d["bin"] = pd.cut(d["prob"], _PROB_BINS, right=False)
    out = d.groupby("bin", observed=True).apply(
        lambda g: pd.Series({
            "n": len(g),
            "pred_mean": round(g["prob"].mean(), 4),
            "real_rate": round(g["won"].mean(), 4),
        }),
        include_groups=False,
    )
    return out.reset_index()


def calibration_summary(
    session: Session,
    model_name: str,
    model_version: Optional[str] = None,
    market: Optional[str] = None,
) -> dict:
    df = prediction_outcomes(session, model_name, model_version, market)
    return {
        "n": int(len(df)),
        "brier": brier_score(df),
        "log_loss": log_loss(df),
    }


def calibration_by(
    session: Session,
    dimension: str,
    model_name: str,
    model_version: Optional[str] = None,
) -> pd.DataFrame:
    """Brier / log-loss sliced by 'league' or 'market'."""
    df = prediction_outcomes(session, model_name, model_version)
    if df.empty:
        return pd.DataFrame(columns=[dimension, "n", "brier", "log_loss"])
    rows = []
    for key, g in df.groupby(dimension, observed=True):
        rows.append({"%s" % dimension: key, "n": len(g),
                     "brier": brier_score(g), "log_loss": log_loss(g)})
    return pd.DataFrame(rows)
