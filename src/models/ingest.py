"""Raw odds ingestion staging — the trust boundary for OCR-extracted odds.

Odds read from bookmaker screenshots (e.g. by an external OCR step) land here
FIRST, with full provenance (screenshot id, captured-at, OCR confidence). A
validation pass marks each row ``validated`` or ``rejected`` (with a reason); only
validated rows are promoted into ``odds_snapshots`` / ``current_odds``.

This keeps a misread price (``2.10`` -> ``21.0``), an unresolved team, a stale or
incomplete capture out of the clean tables — so a wrong number never reaches the
model or a bet slip.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database.base import Base, TimestampMixin


class OddsIngestRaw(TimestampMixin, Base):
    """One captured selection price, as read from a screenshot (pre-validation)."""

    __tablename__ = "odds_ingest_raw"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[Optional[str]] = mapped_column(String(80), index=True)

    # Provenance — where this number came from.
    screenshot_id: Mapped[Optional[str]] = mapped_column(String(255))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float)

    bookmaker: Mapped[str] = mapped_column(String(80), nullable=False)
    home_raw: Mapped[Optional[str]] = mapped_column(String(120))
    away_raw: Mapped[Optional[str]] = mapped_column(String(120))
    league: Mapped[Optional[str]] = mapped_column(String(50))
    season: Mapped[Optional[str]] = mapped_column(String(20))

    market: Mapped[str] = mapped_column(String(40), nullable=False)
    selection: Mapped[str] = mapped_column(String(40), nullable=False)
    line: Mapped[Optional[float]] = mapped_column(Float)
    odd: Mapped[float] = mapped_column(Float, nullable=False)

    captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    kickoff: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # "pending" | "validated" | "rejected" | "promoted"
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False, index=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(String(60))

    match_id: Mapped[Optional[int]] = mapped_column(ForeignKey("matches.id"))
    promoted_snapshot_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("odds_snapshots.id")
    )
