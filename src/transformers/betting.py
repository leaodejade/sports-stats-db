"""DTOs for the betting data layer.

These are the structured payloads an external odds-scraper / model writes to the
database through ``services.betting_repository``. They are source-agnostic: any
bookmaker or model maps onto the same shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OddsDTO(BaseModel):
    """One captured price for one selection."""

    bookmaker: str
    market: str                      # market code, e.g. "1x2", "ou", "btts", "ah"
    selection: str                   # e.g. "home", "draw", "away", "over", "under", "yes"
    odd: float
    line: Optional[float] = None     # e.g. 2.5 for O/U, -0.5 for AH; None for 1x2/btts
    is_opening: bool = False
    is_closing: bool = False
    captured_at: Optional[datetime] = None
    source_url: Optional[str] = None


class PredictionDTO(BaseModel):
    """A model's probability for one selection (pre-match)."""

    model_config = ConfigDict(protected_namespaces=())

    model_name: str = Field(..., min_length=1)
    model_version: str = Field(..., min_length=1)
    market: str
    selection: str
    probability: float = Field(..., ge=0.0, le=1.0)
    line: Optional[float] = None
    predicted_at: Optional[datetime] = None
    extra: Optional[dict] = None


class MarketResultDTO(BaseModel):
    """Settlement of one selection of one market."""

    market: str
    selection: str
    outcome: str                     # "won" | "lost" | "push" | "void"
    line: Optional[float] = None
    result_value: Optional[float] = None
    settled_at: Optional[datetime] = None


class BetDTO(BaseModel):
    """A simulated (paper) bet to record against a stored price."""

    model_config = ConfigDict(protected_namespaces=())

    market: str
    selection: str
    odd_taken: float
    stake: float = Field(..., gt=0.0)
    line: Optional[float] = None
    bookmaker: Optional[str] = None
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    prediction_id: Optional[int] = None
    placed_at: Optional[datetime] = None
