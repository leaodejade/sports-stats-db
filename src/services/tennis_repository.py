"""Repository for idempotent tennis data persistence."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DataSource
from ..models.tennis import (
    TennisMatch,
    TennisMatchStat,
    TennisPlayer,
    TennisRanking,
    TennisSurface,
    TennisTournament,
)
from ..transformers.tennis_transformer import (
    TennisMatchDTO,
    TennisMatchStatDTO,
    TennisPlayerDTO,
    TennisRankingDTO,
    TennisTournamentDTO,
)
from ..utils.logging import get_logger

logger = get_logger(__name__)


def upsert_tennis_player(
    session: Session, source: DataSource, dto: TennisPlayerDTO
) -> TennisPlayer:
    player = session.scalar(
        select(TennisPlayer).where(
            TennisPlayer.source_id == source.id,
            TennisPlayer.external_id == dto.external_id,
        )
    )
    if not player:
        player = TennisPlayer(
            source_id=source.id,
            external_id=dto.external_id,
            name=dto.name,
        )
        session.add(player)

    # Update mutable fields
    player.name = dto.name
    # Country resolution would ideally happen here, but we'll skip for brevity
    # and just set hand/birth_date if we added them to the model (not currently in model)
    return player


def upsert_tennis_surface(session: Session, name: str) -> TennisSurface:
    surface = session.scalar(
        select(TennisSurface).where(TennisSurface.name == name)
    )
    if not surface:
        surface = TennisSurface(name=name)
        session.add(surface)
        session.flush()
    return surface


def upsert_tennis_tournament(
    session: Session, source: DataSource, dto: TennisTournamentDTO
) -> TennisTournament:
    # Use name and start_date as composite key since there's no external_id
    query = select(TennisTournament).where(
        TennisTournament.source_id == source.id,
        TennisTournament.name == dto.name,
    )
    if dto.start_date:
        query = query.where(TennisTournament.start_date == dto.start_date.date())

    tournament = session.scalar(query)

    surface_id = None
    if dto.surface:
        surface = upsert_tennis_surface(session, dto.surface)
        surface_id = surface.id

    if not tournament:
        tournament = TennisTournament(
            source_id=source.id,
            name=dto.name,
        )
        session.add(tournament)

    tournament.name = dto.name
    tournament.surface_id = surface_id
    tournament.category = dto.tour_level
    if dto.start_date:
        tournament.start_date = dto.start_date.date()
        tournament.season_year = dto.start_date.year
    return tournament


def upsert_tennis_match(
    session: Session,
    source: DataSource,
    dto: TennisMatchDTO,
    tournament_id: int,
    winner_id: int,
    loser_id: int,
) -> TennisMatch:
    match = session.scalar(
        select(TennisMatch).where(
            TennisMatch.external_id == dto.external_id,
        )
    )
    if not match:
        match = TennisMatch(
            external_id=dto.external_id,
            tournament_id=tournament_id,
            player1_id=winner_id,
            player2_id=loser_id,
            winner_id=winner_id,
        )
        session.add(match)
        session.flush()

    match.match_date = dto.match_date
    match.score = dto.score
    match.best_of = dto.best_of
    match.round = dto.round

    if dto.winner_stats:
        upsert_tennis_match_stat(session, match.id, winner_id, dto.winner_stats)
    if dto.loser_stats:
        upsert_tennis_match_stat(session, match.id, loser_id, dto.loser_stats)

    return match


def upsert_tennis_match_stat(
    session: Session, match_id: int, player_id: int, dto: TennisMatchStatDTO
) -> TennisMatchStat:
    stat = session.scalar(
        select(TennisMatchStat).where(
            TennisMatchStat.match_id == match_id,
            TennisMatchStat.player_id == player_id,
        )
    )
    if not stat:
        stat = TennisMatchStat(
            match_id=match_id,
            player_id=player_id,
        )
        session.add(stat)

    stat.aces = dto.aces
    stat.double_faults = dto.double_faults
    stat.first_serve_in = dto.first_serve_made
    stat.first_serve_points_won = dto.first_serve_points_won
    stat.second_serve_points_won = dto.second_serve_points_won
    stat.break_points_saved = dto.break_points_saved
    stat.break_points_faced = dto.break_points_faced
    stat.serve_points = dto.first_serve_attempted

    if dto.first_serve_attempted and dto.first_serve_made:
        stat.first_serve_pct = dto.first_serve_made / dto.first_serve_attempted

    return stat


def upsert_tennis_ranking(
    session: Session, player_id: int, dto: TennisRankingDTO
) -> TennisRanking:
    ranking = session.scalar(
        select(TennisRanking).where(
            TennisRanking.player_id == player_id,
            TennisRanking.ranking_date == dto.ranking_date.date(),
        )
    )
    if not ranking:
        ranking = TennisRanking(
            player_id=player_id,
            ranking_date=dto.ranking_date.date(),
        )
        session.add(ranking)

    ranking.rank = dto.rank
    ranking.points = dto.points
    return ranking
