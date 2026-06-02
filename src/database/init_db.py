"""Database bootstrap: create tables and seed reference rows (idempotent)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.engine import Engine

from ..utils.logging import get_logger
from .connection import get_engine, session_scope

# NOTE: models are imported lazily inside the functions below. Importing them at
# module load would create a cycle (models -> database package -> init_db ->
# models), since this module is re-exported from ``database/__init__.py``.

logger = get_logger(__name__)

DEFAULT_SPORTS = ("Football", "Tennis")
DEFAULT_SURFACES = ("Hard", "Clay", "Grass", "Carpet")
DEFAULT_SOURCES = (
    {
        "name": "understat",
        "base_url": "https://understat.com",
        "description": "Expected-goals data for 6 European leagues since 2014/15.",
        "reliability": "high",
    },
)

# Betting reference data (markets + a starter set of bookmakers).
DEFAULT_MARKETS = (
    {"code": "1x2", "name": "Match Result (1X2)"},
    {"code": "ou", "name": "Over/Under Totals"},
    {"code": "btts", "name": "Both Teams To Score"},
    {"code": "ah", "name": "Asian Handicap"},
    {"code": "dc", "name": "Double Chance"},
    {"code": "corners", "name": "Corners"},
    {"code": "cards", "name": "Cards"},
)
DEFAULT_BOOKMAKERS = (
    {"name": "Bet365"},
    {"name": "Betano"},
    {"name": "Pinnacle"},
    {"name": "Superbet"},
)


def create_all(engine: Optional[Engine] = None) -> Engine:
    """Create every table defined on ``Base.metadata`` if it does not exist."""
    from ..models import Base  # lazy import to avoid a circular import

    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    logger.debug("create_all completed (%d tables)", len(Base.metadata.tables))
    return engine


def seed_reference_data(engine: Optional[Engine] = None) -> None:
    """Insert sports, data sources, tennis surfaces, markets and bookmakers."""
    from ..models import (  # lazy import
        Bookmaker,
        DataSource,
        Market,
        Sport,
        TennisSurface,
    )

    engine = engine or get_engine()
    with session_scope(engine) as session:
        for name in DEFAULT_SPORTS:
            if session.scalar(select(Sport).where(Sport.name == name)) is None:
                session.add(Sport(name=name, slug=name.lower()))
        for source in DEFAULT_SOURCES:
            exists = session.scalar(
                select(DataSource).where(DataSource.name == source["name"])
            )
            if exists is None:
                session.add(DataSource(**source))
        for surface in DEFAULT_SURFACES:
            exists = session.scalar(
                select(TennisSurface).where(TennisSurface.name == surface)
            )
            if exists is None:
                session.add(TennisSurface(name=surface))
        for market in DEFAULT_MARKETS:
            if session.scalar(select(Market).where(Market.code == market["code"])) is None:
                session.add(Market(**market))
        for bk in DEFAULT_BOOKMAKERS:
            if session.scalar(select(Bookmaker).where(Bookmaker.name == bk["name"])) is None:
                session.add(Bookmaker(**bk))


def init_db(engine: Optional[Engine] = None) -> Engine:
    """Create all tables and seed reference data. Returns the engine used."""
    from ..models import Base  # lazy import to avoid a circular import

    engine = create_all(engine)
    seed_reference_data(engine)
    logger.info("Database initialised (%d tables)", len(Base.metadata.tables))
    return engine
