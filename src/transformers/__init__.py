"""Transformers: raw source payloads -> validated DTOs."""

from .betting import BetDTO, MarketResultDTO, OddsDTO, PredictionDTO
from .understat_transformer import (
    MatchDTO,
    PlayerMatchDTO,
    PlayerSeasonDTO,
    ShotDTO,
    TeamMatchDTO,
    TeamSeasonDTO,
    transform_league_matches,
    transform_league_players,
    transform_league_teams,
    transform_match_shots,
    transform_roster,
)

__all__ = [
    "MatchDTO",
    "TeamSeasonDTO",
    "TeamMatchDTO",
    "PlayerSeasonDTO",
    "ShotDTO",
    "PlayerMatchDTO",
    "transform_league_matches",
    "transform_league_teams",
    "transform_league_players",
    "transform_match_shots",
    "transform_roster",
    # betting DTOs
    "OddsDTO",
    "PredictionDTO",
    "MarketResultDTO",
    "BetDTO",
]
