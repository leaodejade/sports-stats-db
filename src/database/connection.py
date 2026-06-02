"""Engine and session management.

The module keeps a lazily-created default engine/session-factory bound to the
configured ``DATABASE_URL`` but also lets callers pass an explicit engine,
which is what the test-suite uses to run against an isolated SQLite database.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..utils.config import get_settings
from ..utils.logging import get_logger

logger = get_logger(__name__)

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def _enable_sqlite_fk(engine: Engine) -> None:
    """Enforce foreign keys on SQLite (off by default)."""
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_db_engine(database_url: str, echo: bool = False) -> Engine:
    """Create a brand-new engine for an explicit URL (used by tests)."""
    engine = create_engine(database_url, echo=echo, future=True)
    _enable_sqlite_fk(engine)
    return engine


def get_engine(echo: bool = False) -> Engine:
    """Return the lazily-created default engine for the configured database."""
    global _engine
    if _engine is None:
        url = get_settings().resolved_database_url
        _engine = create_db_engine(url, echo=echo)
        logger.debug("Created default engine for %s", url)
    return _engine


def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker:
    """Return a session factory bound to ``engine`` (or the default engine)."""
    global _session_factory
    if engine is not None:
        return sessionmaker(
            bind=engine, autoflush=False, expire_on_commit=False, future=True
        )
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _session_factory


@contextmanager
def session_scope(engine: Optional[Engine] = None) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error, always close."""
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
