"""Idempotent upserts for football entities.

Every function looks an entity up by its natural/unique key and either updates
it in place or inserts a new row, so ingestion can run repeatedly without
creating duplicates. IDs are assigned via ``session.flush()`` where callers
need them immediately (e.g. to wire foreign keys).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Competition,
    DataSource,
    FundamentalNote,
    Match,
    MatchContext,
    MatchPlayerStat,
    MatchTeamStat,
    Player,
    PlayerSeasonStat,
    Season,
    Shot,
    Sport,
    Standing,
    Team,
    TeamAlias,
)

# Tokens dropped when normalising a club name (so "Arsenal FC" == "Arsenal").
_DROP_TOKENS = {"fc", "afc", "cf", "sc", "club", "the", "de", "ud", "cd"}


def normalize_team_name(name: Optional[str]) -> str:
    """Lower-case, strip accents/punctuation and common club tokens.

    Conservative on purpose: it only folds case/accents/punctuation and a small
    set of generic suffixes, so distinct clubs are never merged by accident.
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    tokens = [t for t in text.split() if t and t not in _DROP_TOKENS]
    return " ".join(tokens)


def record_team_alias(
    session: Session,
    team: Team,
    raw_name: Optional[str],
    source: Optional[DataSource] = None,
) -> None:
    """Map ``normalize_team_name(raw_name)`` -> ``team`` (idempotent, safe).

    Skips empty names and refuses to re-point an alias already owned by a
    different team (avoids accidental merges).
    """
    alias = normalize_team_name(raw_name)
    if not alias:
        return
    existing = session.scalar(
        select(TeamAlias).where(
            TeamAlias.sport_id == team.sport_id, TeamAlias.alias == alias
        )
    )
    if existing is not None:
        return
    session.add(
        TeamAlias(
            sport_id=team.sport_id,
            team_id=team.id,
            source_id=source.id if source else None,
            alias=alias,
        )
    )
    session.flush()


def find_team(session: Session, sport: Sport, name: Optional[str]) -> Optional[Team]:
    """Resolve a team by name WITHOUT creating one (exact name, then alias)."""
    if not name:
        return None
    team = session.scalar(
        select(Team).where(Team.sport_id == sport.id, Team.name == name)
    )
    if team is not None:
        return team
    alias = normalize_team_name(name)
    if not alias:
        return None
    hit = session.scalar(
        select(TeamAlias).where(
            TeamAlias.sport_id == sport.id, TeamAlias.alias == alias
        )
    )
    return session.get(Team, hit.team_id) if hit is not None else None
from ..transformers import (
    MatchDTO,
    PlayerMatchDTO,
    PlayerSeasonDTO,
    ShotDTO,
    TeamMatchDTO,
    TeamSeasonDTO,
)


# ---------------------------------------------------------------------------
# Teams & players
# ---------------------------------------------------------------------------
def get_or_create_team(
    session: Session,
    sport: Sport,
    source: DataSource,
    external_id: Optional[str],
    name: Optional[str],
) -> Team:
    team = None
    if external_id:
        team = session.scalar(
            select(Team).where(
                Team.sport_id == sport.id, Team.external_id == external_id
            )
        )
    # Resolve by exact name, then by known alias, before creating a new row.
    if team is None and name:
        team = find_team(session, sport, name)
    if team is None:
        team = Team(
            sport_id=sport.id,
            source_id=source.id,
            external_id=external_id,
            name=name or external_id or "Unknown",
        )
        session.add(team)
        session.flush()
        record_team_alias(session, team, team.name, source)
        record_team_alias(session, team, name, source)
        return team

    # Keep the human name / external id fresh if we learned a better value.
    if name and team.name != name:
        team.name = name
    if external_id and not team.external_id:
        team.external_id = external_id
    # Learn this spelling so future lookups (and other sources) resolve to it.
    record_team_alias(session, team, name, source)
    return team


def get_or_create_player(
    session: Session,
    sport: Sport,
    source: DataSource,
    external_id: Optional[str],
    name: Optional[str],
    position: Optional[str] = None,
    team: Optional[Team] = None,
) -> Player:
    player = None
    if external_id:
        player = session.scalar(
            select(Player).where(
                Player.sport_id == sport.id, Player.external_id == external_id
            )
        )
    if player is None and name and not external_id:
        player = session.scalar(
            select(Player).where(Player.sport_id == sport.id, Player.name == name)
        )
    if player is None:
        player = Player(
            sport_id=sport.id,
            source_id=source.id,
            external_id=external_id,
            name=name or "Unknown",
            position=position,
            team_id=team.id if team else None,
        )
        session.add(player)
        session.flush()
        return player

    if name and player.name != name:
        player.name = name
    if position and not player.position:
        player.position = position
    if team and not player.team_id:
        player.team_id = team.id
    return player


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------
def upsert_match(
    session: Session,
    competition: Competition,
    season: Season,
    source: DataSource,
    dto: MatchDTO,
    home_team: Team,
    away_team: Team,
) -> Match:
    match = None
    if dto.external_id:
        match = session.scalar(
            select(Match).where(
                Match.source_id == source.id, Match.external_id == dto.external_id
            )
        )
    if match is None:
        match = Match(source_id=source.id, external_id=dto.external_id)
        session.add(match)

    match.competition_id = competition.id
    match.season_id = season.id
    match.home_team_id = home_team.id
    match.away_team_id = away_team.id
    match.match_datetime = dto.match_datetime
    match.home_goals = dto.home_goals
    match.away_goals = dto.away_goals
    match.home_xg = dto.home_xg
    match.away_xg = dto.away_xg
    match.forecast_w = dto.forecast_w
    match.forecast_d = dto.forecast_d
    match.forecast_l = dto.forecast_l
    match.is_result = dto.is_result
    session.flush()
    return match


def build_match_lookup(session: Session, season: Season) -> dict[tuple[int, object], int]:
    """Map ``(team_id, match_date.date())`` -> ``match_id`` for a season.

    Used to attach team-history rows (which only carry a date) to the right
    match row.
    """
    lookup: dict[tuple[int, object], int] = {}
    matches = session.scalars(
        select(Match).where(Match.season_id == season.id)
    ).all()
    for match in matches:
        if match.match_datetime is None:
            continue
        day = match.match_datetime.date()
        lookup[(match.home_team_id, day)] = match.id
        lookup[(match.away_team_id, day)] = match.id
    return lookup


# ---------------------------------------------------------------------------
# Per-match team stats / standings
# ---------------------------------------------------------------------------
def upsert_match_team_stat(
    session: Session,
    season: Season,
    team: Team,
    dto: TeamMatchDTO,
    match_id: Optional[int],
) -> MatchTeamStat:
    stat = session.scalar(
        select(MatchTeamStat).where(
            MatchTeamStat.season_id == season.id,
            MatchTeamStat.team_id == team.id,
            MatchTeamStat.match_date == dto.match_date,
        )
    )
    if stat is None:
        stat = MatchTeamStat(
            season_id=season.id, team_id=team.id, match_date=dto.match_date
        )
        session.add(stat)

    stat.match_id = match_id
    stat.is_home = dto.is_home
    stat.goals = dto.goals
    stat.conceded = dto.conceded
    stat.xg = dto.xg
    stat.xga = dto.xga
    stat.npxg = dto.npxg
    stat.npxg_diff = dto.npxg_diff
    stat.ppda = dto.ppda
    stat.ppda_allowed = dto.ppda_allowed
    stat.deep = dto.deep
    stat.deep_allowed = dto.deep_allowed
    stat.xpts = dto.xpts
    stat.points = dto.points
    stat.result = dto.result
    return stat


def upsert_standing(
    session: Session,
    competition: Competition,
    season: Season,
    team: Team,
    dto: TeamSeasonDTO,
    position: Optional[int] = None,
) -> Standing:
    standing = session.scalar(
        select(Standing).where(
            Standing.season_id == season.id, Standing.team_id == team.id
        )
    )
    if standing is None:
        standing = Standing(
            competition_id=competition.id, season_id=season.id, team_id=team.id
        )
        session.add(standing)

    standing.position = position
    standing.matches_played = dto.matches_played
    standing.wins = dto.wins
    standing.draws = dto.draws
    standing.losses = dto.losses
    standing.goals_for = dto.goals_for
    standing.goals_against = dto.goals_against
    standing.goal_diff = (dto.goals_for or 0) - (dto.goals_against or 0)
    standing.points = dto.points
    standing.xg = dto.xg
    standing.xga = dto.xga
    standing.xg_diff = round((dto.xg or 0.0) - (dto.xga or 0.0), 4)
    standing.npxg = dto.npxg
    standing.xpts = dto.xpts
    standing.deep = dto.deep
    standing.form = dto.form
    return standing


def upsert_player_season(
    session: Session,
    competition: Competition,
    season: Season,
    player: Player,
    team: Optional[Team],
    dto: PlayerSeasonDTO,
) -> PlayerSeasonStat:
    row = session.scalar(
        select(PlayerSeasonStat).where(
            PlayerSeasonStat.season_id == season.id,
            PlayerSeasonStat.player_id == player.id,
        )
    )
    if row is None:
        row = PlayerSeasonStat(
            competition_id=competition.id, season_id=season.id, player_id=player.id
        )
        session.add(row)

    row.team_id = team.id if team else None
    row.games = dto.games
    row.minutes = dto.minutes
    row.goals = dto.goals
    row.assists = dto.assists
    row.shots = dto.shots
    row.key_passes = dto.key_passes
    row.xg = dto.xg
    row.xa = dto.xa
    row.npg = dto.npg
    row.npxg = dto.npxg
    row.xg_chain = dto.xg_chain
    row.xg_buildup = dto.xg_buildup
    row.position = dto.position
    row.yellow_cards = dto.yellow_cards
    row.red_cards = dto.red_cards
    return row


# ---------------------------------------------------------------------------
# Shots & per-match player stats (deep ingestion)
# ---------------------------------------------------------------------------
def upsert_shot(
    session: Session,
    source: DataSource,
    dto: ShotDTO,
    match_id: Optional[int],
    player_id: Optional[int],
    team_id: Optional[int],
) -> Shot:
    shot = None
    if dto.external_id:
        shot = session.scalar(
            select(Shot).where(
                Shot.source_id == source.id, Shot.external_id == dto.external_id
            )
        )
    if shot is None:
        shot = Shot(source_id=source.id, external_id=dto.external_id)
        session.add(shot)

    shot.match_id = match_id
    shot.player_id = player_id
    shot.team_id = team_id
    shot.minute = dto.minute
    shot.x = dto.x
    shot.y = dto.y
    shot.xg = dto.xg
    shot.result = dto.result
    shot.situation = dto.situation
    shot.shot_type = dto.shot_type
    shot.is_home = dto.is_home
    shot.last_action = dto.last_action
    shot.player_assisted = dto.player_assisted
    return shot


def upsert_match_player_stat(
    session: Session,
    match_id: int,
    player: Player,
    team_id: Optional[int],
    dto: PlayerMatchDTO,
) -> MatchPlayerStat:
    row = session.scalar(
        select(MatchPlayerStat).where(
            MatchPlayerStat.match_id == match_id,
            MatchPlayerStat.player_id == player.id,
        )
    )
    if row is None:
        row = MatchPlayerStat(match_id=match_id, player_id=player.id)
        session.add(row)

    row.team_id = team_id
    row.minutes = dto.minutes
    row.goals = dto.goals
    row.own_goals = dto.own_goals
    row.assists = dto.assists
    row.shots = dto.shots
    row.key_passes = dto.key_passes
    row.xg = dto.xg
    row.xa = dto.xa
    row.npg = dto.npg
    row.npxg = dto.npxg
    row.xg_chain = dto.xg_chain
    row.xg_buildup = dto.xg_buildup
    row.position = dto.position
    row.yellow_cards = dto.yellow_cards
    row.red_cards = dto.red_cards
    return row


# ---------------------------------------------------------------------------
# Pre-match context & fundamentals
# ---------------------------------------------------------------------------
def upsert_match_context(session: Session, match_id: int, **fields) -> MatchContext:
    """Idempotent per-match context (referee, weather, importance, travel...)."""
    ctx = session.scalar(
        select(MatchContext).where(MatchContext.match_id == match_id)
    )
    if ctx is None:
        ctx = MatchContext(match_id=match_id)
        session.add(ctx)
    allowed = {
        "referee", "attendance", "importance", "weather",
        "travel_km_home", "travel_km_away",
    }
    for key, value in fields.items():
        if key in allowed:
            setattr(ctx, key, value)
    session.flush()
    return ctx


def upsert_fundamental_note(
    session: Session,
    kind: str,
    match_id: Optional[int] = None,
    team_id: Optional[int] = None,
    payload: Optional[dict] = None,
    source: Optional[DataSource] = None,
    source_url: Optional[str] = None,
    source_quality: Optional[str] = None,
    as_of: Optional[datetime] = None,
) -> FundamentalNote:
    """Structured note (line-up/injury/suspension), one per (match, team, kind)."""
    note = session.scalar(
        select(FundamentalNote).where(
            FundamentalNote.match_id == match_id,
            FundamentalNote.team_id == team_id,
            FundamentalNote.kind == kind,
        )
    )
    if note is None:
        note = FundamentalNote(match_id=match_id, team_id=team_id, kind=kind)
        session.add(note)
    note.payload = payload
    note.source_id = source.id if source else None
    note.source_url = source_url
    note.source_quality = source_quality
    note.as_of = as_of
    session.flush()
    return note
