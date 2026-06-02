"""Tests for alembic migrations."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from alembic import command
from alembic.config import Config


def test_alembic_upgrade_head(tmp_path):
    """Test that alembic upgrade head correctly creates the database schema."""
    db_file = tmp_path / "test_migrations.db"
    db_url = f"sqlite:///{db_file}"

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # Run migrations
    command.upgrade(alembic_cfg, "head")

    # Inspect schema
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in result}

    # Check that basic tables exist
    assert "sports" in tables
    assert "countries" in tables
    assert "teams" in tables
    assert "players" in tables
    assert "tennis_players" in tables
    assert "tennis_matches" in tables
    assert "alembic_version" in tables
