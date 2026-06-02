"""Pre-match feature store.

One row holds the features known *before kickoff* for a single match, computed
strictly from earlier matches. This is the leakage-free input a model should
consume — never ``matches.forecast_*`` (a post-match retrodiction) nor the
target match's own xG/result.

A handful of core features are typed columns (so they are queryable in SQL);
anything experimental goes in ``extra`` (JSON). ``feature_set_version`` lets new
feature definitions coexist with old ones for reproducible backtests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..database.base import Base, TimestampMixin


class PrematchFeature(TimestampMixin, Base):
    __tablename__ = "prematch_features"
    __table_args__ = (
        UniqueConstraint("match_id", "feature_set_version", name="uq_prematch_feature"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    feature_set_version: Mapped[str] = mapped_column(String(40), nullable=False)
    # Cut-off instant: every feature uses only data strictly before this.
    as_of: Mapped[Optional[datetime]] = mapped_column(DateTime)
    window: Mapped[Optional[int]] = mapped_column(Integer)

    # Rolling form / strength (computed over the last `window` prior matches).
    home_form: Mapped[Optional[float]] = mapped_column(Float)   # pts / game
    away_form: Mapped[Optional[float]] = mapped_column(Float)
    home_xgf: Mapped[Optional[float]] = mapped_column(Float)    # xG created
    home_xga: Mapped[Optional[float]] = mapped_column(Float)    # xG conceded
    away_xgf: Mapped[Optional[float]] = mapped_column(Float)
    away_xga: Mapped[Optional[float]] = mapped_column(Float)

    home_rest_days: Mapped[Optional[int]] = mapped_column(Integer)
    away_rest_days: Mapped[Optional[int]] = mapped_column(Integer)
    # Sample sizes — use to enforce a minimum history before trusting a row.
    home_hist_n: Mapped[Optional[int]] = mapped_column(Integer)
    away_hist_n: Mapped[Optional[int]] = mapped_column(Integer)

    extra: Mapped[Optional[dict]] = mapped_column(JSON)
