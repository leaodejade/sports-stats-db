"""Tests for the one-shot bootstrap service (audit / v1 convenience)."""

from __future__ import annotations

from sqlalchemy import func, select

from src.database import get_session_factory
from src.models import Match, PrematchFeature
from src.services.bootstrap import bootstrap


def test_bootstrap_ingests_and_builds_features(engine, fake_collector):
    report = bootstrap(
        collector=fake_collector, engine=engine,
        leagues=["EPL"], seasons=["2023"], with_features=True,
    )
    assert report.as_dict()["ingested"] == 1
    assert report.as_dict()["failed"] == 0

    session = get_session_factory(engine)()
    try:
        assert session.scalar(select(func.count()).select_from(Match)) == 2
        # features built for both finished matches
        assert report.features_built == 2
        assert session.scalar(select(func.count()).select_from(PrematchFeature)) == 2
    finally:
        session.close()


def test_bootstrap_can_skip_features(engine, fake_collector):
    report = bootstrap(
        collector=fake_collector, engine=engine,
        leagues=["EPL"], seasons=["2023"], with_features=False,
    )
    assert report.features_built == 0
    session = get_session_factory(engine)()
    try:
        assert session.scalar(select(func.count()).select_from(PrematchFeature)) == 0
    finally:
        session.close()


def test_bootstrap_is_idempotent(engine, fake_collector):
    bootstrap(collector=fake_collector, engine=engine,
                        leagues=["EPL"], seasons=["2023"])
    bootstrap(collector=fake_collector, engine=engine,
                        leagues=["EPL"], seasons=["2023"])  # run twice
    session = get_session_factory(engine)()
    try:
        assert session.scalar(select(func.count()).select_from(Match)) == 2  # no dupes
        assert session.scalar(select(func.count()).select_from(PrematchFeature)) == 2
    finally:
        session.close()
