"""Betting data layer: bookmakers, markets, odds time-series, settlement,
model predictions, simulated bets and a bankroll ledger.

Designed to be the persistence layer for an external system that scrapes odds in
real time and runs its own modelling. This module only *stores and serves* data;
it does not collect odds nor model anything.

Design notes
------------
* ``OddsSnapshot`` is **append-only** (full history of every captured price);
  ``CurrentOdds`` keeps just the latest price per (match, bookmaker, market,
  selection, line) for fast reads.
* ``selection`` + ``line`` keep markets flexible: 1X2 uses
  ``home``/``draw``/``away`` with ``line=None``; Over/Under uses
  ``over``/``under`` with ``line=2.5``; Asian Handicap uses e.g.
  ``home``/``away`` with ``line=-0.5``; BTTS uses ``yes``/``no``.
* Enum-like columns are plain ``String`` (matching the existing schema style,
  e.g. ``Standing.form``), with allowed values documented next to each.
* Upserts are done at the application layer via a SELECT-then-write (see
  ``services/betting_repository.py``), so a ``NULL`` ``line`` is handled
  explicitly; the ``UniqueConstraint``s are a best-effort safety net.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database.base import Base, TimestampMixin


# ---------------------------------------------------------------------------
# Reference / dimension tables
# ---------------------------------------------------------------------------
class Bookmaker(TimestampMixin, Base):
    __tablename__ = "bookmakers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    slug: Mapped[Optional[str]] = mapped_column(String(80), unique=True)
    country: Mapped[Optional[str]] = mapped_column(String(60))
    is_exchange: Mapped[bool] = mapped_column(Boolean, default=False)


class Market(TimestampMixin, Base):
    """A betting market type (1X2, Over/Under, BTTS, Asian Handicap, ...)."""

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(primary_key=True)
    # e.g. "1x2", "ou", "btts", "ah", "dc", "corners", "cards"
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))


# ---------------------------------------------------------------------------
# Odds
# ---------------------------------------------------------------------------
class OddsSnapshot(TimestampMixin, Base):
    """One captured price for one selection, at one instant (append-only)."""

    __tablename__ = "odds_snapshots"
    __table_args__ = (
        Index(
            "ix_odds_snap_match_market_sel_time",
            "match_id", "market_id", "selection", "captured_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"), nullable=False)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), nullable=False)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))

    selection: Mapped[str] = mapped_column(String(40), nullable=False)
    line: Mapped[Optional[float]] = mapped_column(Float)
    odd: Mapped[float] = mapped_column(Float, nullable=False)
    implied_prob: Mapped[Optional[float]] = mapped_column(Float)

    is_opening: Mapped[bool] = mapped_column(Boolean, default=False)
    is_closing: Mapped[bool] = mapped_column(Boolean, default=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(500))

    bookmaker: Mapped["Bookmaker"] = relationship()
    market: Mapped["Market"] = relationship()


class CurrentOdds(TimestampMixin, Base):
    """Latest known price per (match, bookmaker, market, selection, line)."""

    __tablename__ = "current_odds"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "bookmaker_id", "market_id", "selection", "line",
            name="uq_current_odds",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"), nullable=False)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), nullable=False)

    selection: Mapped[str] = mapped_column(String(40), nullable=False)
    line: Mapped[Optional[float]] = mapped_column(Float)
    odd: Mapped[float] = mapped_column(Float, nullable=False)
    implied_prob: Mapped[Optional[float]] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    bookmaker: Mapped["Bookmaker"] = relationship()
    market: Mapped["Market"] = relationship()


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
class MarketResult(TimestampMixin, Base):
    """Settled outcome of one selection of one market for a match."""

    __tablename__ = "market_results"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "market_id", "selection", "line", name="uq_market_result"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), nullable=False)

    selection: Mapped[str] = mapped_column(String(40), nullable=False)
    line: Mapped[Optional[float]] = mapped_column(Float)
    # "won" | "lost" | "push" | "void"
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    result_value: Mapped[Optional[float]] = mapped_column(Float)  # e.g. total goals
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    market: Mapped["Market"] = relationship()


# ---------------------------------------------------------------------------
# Model predictions
# ---------------------------------------------------------------------------
class Prediction(TimestampMixin, Base):
    """A model's probability for one selection, versioned and timestamped.

    This is the PRE-match prediction store the external model writes to. It is
    deliberately separate from ``matches.forecast_*`` (which is Understat's
    POST-match retrodiction and must never be used as a pre-match feature).
    """

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "model_name", "model_version", "market_id", "selection", "line",
            name="uq_prediction",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(80), nullable=False)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), nullable=False)

    selection: Mapped[str] = mapped_column(String(40), nullable=False)
    line: Mapped[Optional[float]] = mapped_column(Float)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    fair_odd: Mapped[Optional[float]] = mapped_column(Float)
    edge: Mapped[Optional[float]] = mapped_column(Float)
    predicted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    extra: Mapped[Optional[dict]] = mapped_column(JSON)

    market: Mapped["Market"] = relationship()


# ---------------------------------------------------------------------------
# Simulated bets + bankroll ledger
# ---------------------------------------------------------------------------
class SimulatedBet(TimestampMixin, Base):
    """A (paper) bet placed against a stored price. No real-money promotion."""

    __tablename__ = "simulated_bets"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    bookmaker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bookmakers.id"))
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), nullable=False)
    prediction_id: Mapped[Optional[int]] = mapped_column(ForeignKey("predictions.id"))

    selection: Mapped[str] = mapped_column(String(40), nullable=False)
    line: Mapped[Optional[float]] = mapped_column(Float)
    odd_taken: Mapped[float] = mapped_column(Float, nullable=False)
    stake: Mapped[float] = mapped_column(Float, nullable=False)
    # "pending" | "won" | "lost" | "void" | "push" | "cashout"
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    pnl: Mapped[Optional[float]] = mapped_column(Float)
    model_name: Mapped[Optional[str]] = mapped_column(String(80))
    model_version: Mapped[Optional[str]] = mapped_column(String(40))

    bookmaker: Mapped[Optional["Bookmaker"]] = relationship()
    market: Mapped["Market"] = relationship()


class BetDecision(TimestampMixin, Base):
    """Audit trail of every selection a backtest *considered*.

    Records both placed and rejected decisions (with a reason and the filters in
    force), so a backtest is reproducible and "why didn't it bet here?" is
    answerable.
    """

    __tablename__ = "bet_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_label: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), nullable=False)
    selection: Mapped[str] = mapped_column(String(40), nullable=False)
    line: Mapped[Optional[float]] = mapped_column(Float)

    model_name: Mapped[Optional[str]] = mapped_column(String(80))
    model_version: Mapped[Optional[str]] = mapped_column(String(40))
    probability: Mapped[Optional[float]] = mapped_column(Float)
    odd: Mapped[Optional[float]] = mapped_column(Float)
    ev: Mapped[Optional[float]] = mapped_column(Float)

    decided: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(40))  # why bet / why not
    outcome: Mapped[Optional[str]] = mapped_column(String(10))  # won/lost/push/void
    pnl: Mapped[Optional[float]] = mapped_column(Float)
    filters: Mapped[Optional[dict]] = mapped_column(JSON)


class BankrollTransaction(TimestampMixin, Base):
    """Signed movements of the (paper) bankroll, in chronological order."""

    __tablename__ = "bankroll_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # "deposit" | "withdraw" | "stake" | "return" | "adjust"
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)  # +credit / -debit
    balance_after: Mapped[Optional[float]] = mapped_column(Float)
    bet_id: Mapped[Optional[int]] = mapped_column(ForeignKey("simulated_bets.id"))
    note: Mapped[Optional[str]] = mapped_column(String(255))
