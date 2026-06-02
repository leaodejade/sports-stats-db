"""Transform raw Jeff Sackmann payloads into validated DTOs for Tennis."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel

from .base import to_int, to_float, clean_str


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
class TennisPlayerDTO(BaseModel):
    external_id: str
    name: str
    country_code: Optional[str] = None
    hand: Optional[str] = None
    birth_date: Optional[datetime] = None
    height_cm: Optional[float] = None


class TennisTournamentDTO(BaseModel):
    external_id: str
    name: str
    surface: Optional[str] = None
    tour_level: Optional[str] = None
    start_date: Optional[datetime] = None


class TennisMatchStatDTO(BaseModel):
    aces: Optional[int] = None
    double_faults: Optional[int] = None
    first_serve_made: Optional[int] = None
    first_serve_attempted: Optional[int] = None
    first_serve_points_won: Optional[int] = None
    second_serve_points_won: Optional[int] = None
    break_points_saved: Optional[int] = None
    break_points_faced: Optional[int] = None


class TennisMatchDTO(BaseModel):
    external_id: str
    tournament_external_id: str
    match_num: int
    match_date: Optional[datetime] = None
    winner_external_id: str
    loser_external_id: str
    score: Optional[str] = None
    best_of: Optional[int] = None
    round: Optional[str] = None
    minutes: Optional[int] = None
    winner_stats: Optional[TennisMatchStatDTO] = None
    loser_stats: Optional[TennisMatchStatDTO] = None


class TennisRankingDTO(BaseModel):
    player_external_id: str
    ranking_date: datetime
    rank: int
    points: Optional[int] = None


class TennisSurfaceDTO(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# Transformation Functions
# ---------------------------------------------------------------------------

from datetime import timezone

def _parse_yyyymmdd(date_str: Any) -> Optional[datetime]:
    s = clean_str(date_str)
    if not s or len(s) != 8:
        return None
    try:
        dt = datetime.strptime(s, "%Y%m%d")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def transform_tennis_players(raw_players: List[Dict[str, Any]]) -> List[TennisPlayerDTO]:
    dtos = []
    for raw in raw_players:
        player_id = clean_str(raw.get("player_id"))
        if not player_id:
            continue

        first = clean_str(raw.get("name_first")) or ""
        last = clean_str(raw.get("name_last")) or ""
        name = f"{first} {last}".strip()
        if not name:
            continue

        dtos.append(TennisPlayerDTO(
            external_id=player_id,
            name=name,
            country_code=clean_str(raw.get("ioc")),
            hand=clean_str(raw.get("hand")),
            birth_date=_parse_yyyymmdd(raw.get("dob")),
            height_cm=to_float(raw.get("height"))
        ))
    return dtos

def transform_tennis_matches(raw_matches: List[Dict[str, Any]]) -> List[TennisMatchDTO]:
    dtos = []
    for raw in raw_matches:
        match_id = clean_str(raw.get("match_num"))
        tourney_id = clean_str(raw.get("tourney_id"))
        winner_id = clean_str(raw.get("winner_id"))
        loser_id = clean_str(raw.get("loser_id"))

        if not (match_id and tourney_id and winner_id and loser_id):
            continue

        external_id = f"{tourney_id}_{match_id}"

        winner_stats = None
        if to_int(raw.get("w_svpt")) is not None:
            winner_stats = TennisMatchStatDTO(
                aces=to_int(raw.get("w_ace")),
                double_faults=to_int(raw.get("w_df")),
                first_serve_attempted=to_int(raw.get("w_svpt")),
                first_serve_made=to_int(raw.get("w_1stIn")),
                first_serve_points_won=to_int(raw.get("w_1stWon")),
                second_serve_points_won=to_int(raw.get("w_2ndWon")),
                break_points_saved=to_int(raw.get("w_bpSaved")),
                break_points_faced=to_int(raw.get("w_bpFaced"))
            )

        loser_stats = None
        if to_int(raw.get("l_svpt")) is not None:
            loser_stats = TennisMatchStatDTO(
                aces=to_int(raw.get("l_ace")),
                double_faults=to_int(raw.get("l_df")),
                first_serve_attempted=to_int(raw.get("l_svpt")),
                first_serve_made=to_int(raw.get("l_1stIn")),
                first_serve_points_won=to_int(raw.get("l_1stWon")),
                second_serve_points_won=to_int(raw.get("l_2ndWon")),
                break_points_saved=to_int(raw.get("l_bpSaved")),
                break_points_faced=to_int(raw.get("l_bpFaced"))
            )

        tourney_date = _parse_yyyymmdd(raw.get("tourney_date"))

        dtos.append(TennisMatchDTO(
            external_id=external_id,
            tournament_external_id=tourney_id,
            match_num=to_int(match_id),
            match_date=tourney_date,
            winner_external_id=winner_id,
            loser_external_id=loser_id,
            score=clean_str(raw.get("score")),
            best_of=to_int(raw.get("best_of")),
            round=clean_str(raw.get("round")),
            minutes=to_int(raw.get("minutes")),
            winner_stats=winner_stats,
            loser_stats=loser_stats
        ))
    return dtos

def extract_tournaments(raw_matches: List[Dict[str, Any]]) -> List[TennisTournamentDTO]:
    tournaments = {}
    for raw in raw_matches:
        tourney_id = clean_str(raw.get("tourney_id"))
        if not tourney_id or tourney_id in tournaments:
            continue

        name = clean_str(raw.get("tourney_name"))
        if not name:
            continue

        tournaments[tourney_id] = TennisTournamentDTO(
            external_id=tourney_id,
            name=name,
            surface=clean_str(raw.get("surface")),
            tour_level=clean_str(raw.get("tourney_level")),
            start_date=_parse_yyyymmdd(raw.get("tourney_date"))
        )
    return list(tournaments.values())

def transform_tennis_rankings(raw_rankings: List[Dict[str, Any]]) -> List[TennisRankingDTO]:
    dtos = []
    for raw in raw_rankings:
        date_obj = _parse_yyyymmdd(raw.get("ranking_date"))
        player_id = clean_str(raw.get("player"))
        rank = to_int(raw.get("rank"))

        if not (date_obj and player_id and rank):
            continue

        dtos.append(TennisRankingDTO(
            player_external_id=player_id,
            ranking_date=date_obj,
            rank=rank,
            points=to_int(raw.get("points"))
        ))
    return dtos
