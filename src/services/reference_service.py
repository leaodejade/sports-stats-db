"""Get-or-create helpers for reference/dimension entities.

These keep ingestion idempotent: re-running the same league/season never
duplicates a sport, source, competition or season.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Competition, Country, DataSource, Season, Sport

# Understat league code -> (display name, country name)
UNDERSTAT_LEAGUE_META: dict[str, tuple[str, str]] = {
    "EPL": ("Premier League", "England"),
    "La_liga": ("La Liga", "Spain"),
    "Bundesliga": ("Bundesliga", "Germany"),
    "Serie_A": ("Serie A", "Italy"),
    "Ligue_1": ("Ligue 1", "France"),
    "RFPL": ("Russian Premier League", "Russia"),
}


def get_or_create_sport(session: Session, name: str = "Football") -> Sport:
    sport = session.scalar(select(Sport).where(Sport.name == name))
    if sport is None:
        sport = Sport(name=name, slug=name.lower())
        session.add(sport)
        session.flush()
    return sport


def get_or_create_source(session: Session, name: str = "understat") -> DataSource:
    source = session.scalar(select(DataSource).where(DataSource.name == name))
    if source is None:
        source = DataSource(name=name)
        session.add(source)
        session.flush()
    return source


def get_or_create_country(session: Session, name: Optional[str]) -> Optional[Country]:
    if not name:
        return None
    country = session.scalar(select(Country).where(Country.name == name))
    if country is None:
        country = Country(name=name)
        session.add(country)
        session.flush()
    return country


def get_or_create_competition(
    session: Session,
    sport: Sport,
    source: DataSource,
    league_code: str,
) -> Competition:
    """Resolve a competition from an Understat league code."""
    competition = session.scalar(
        select(Competition).where(Competition.code == league_code)
    )
    if competition is not None:
        return competition

    name, country_name = UNDERSTAT_LEAGUE_META.get(
        league_code, (league_code.replace("_", " "), None)
    )
    country = get_or_create_country(session, country_name)
    competition = Competition(
        sport_id=sport.id,
        source_id=source.id,
        country_id=country.id if country else None,
        name=name,
        code=league_code,
        external_id=league_code,
    )
    session.add(competition)
    session.flush()
    return competition


def _season_label(external_season: str) -> tuple[str, Optional[int], Optional[int]]:
    """`'2023'` -> ('2023/2024', 2023, 2024)."""
    try:
        start = int(external_season)
        return f"{start}/{start + 1}", start, start + 1
    except (TypeError, ValueError):
        return str(external_season), None, None


def get_or_create_season(
    session: Session,
    competition: Competition,
    external_season: str,
) -> Season:
    external_season = str(external_season)
    season = session.scalar(
        select(Season).where(
            Season.competition_id == competition.id,
            Season.external_season == external_season,
        )
    )
    if season is not None:
        return season

    label, year_start, year_end = _season_label(external_season)
    season = Season(
        competition_id=competition.id,
        external_season=external_season,
        label=label,
        year_start=year_start,
        year_end=year_end,
    )
    session.add(season)
    session.flush()
    return season
