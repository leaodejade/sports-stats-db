"""Transform raw Understat payloads into validated, source-agnostic DTOs.

Each function takes the exact structure returned by ``understatapi`` and emits
Pydantic models that the ingestion service can upsert without knowing anything
about Understat's quirks (string numbers, ``h``/``a`` flags, nested ppda...).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from .base import (
    clean_str,
    normalize_ppda,
    parse_datetime,
    to_bool_home,
    to_float,
    to_int,
)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
class MatchDTO(BaseModel):
    external_id: Optional[str] = None
    home_external_id: Optional[str] = None
    home_name: Optional[str] = None
    away_external_id: Optional[str] = None
    away_name: Optional[str] = None
    match_datetime: Optional[datetime] = None
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    home_xg: Optional[float] = None
    away_xg: Optional[float] = None
    forecast_w: Optional[float] = None
    forecast_d: Optional[float] = None
    forecast_l: Optional[float] = None
    is_result: bool = False


class TeamSeasonDTO(BaseModel):
    team_external_id: Optional[str] = None
    team_name: Optional[str] = None
    matches_played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0
    xg: float = 0.0
    xga: float = 0.0
    npxg: float = 0.0
    xpts: float = 0.0
    deep: int = 0
    form: Optional[str] = None


class TeamMatchDTO(BaseModel):
    team_external_id: Optional[str] = None
    team_name: Optional[str] = None
    match_date: Optional[datetime] = None
    is_home: Optional[bool] = None
    goals: Optional[int] = None
    conceded: Optional[int] = None
    xg: Optional[float] = None
    xga: Optional[float] = None
    npxg: Optional[float] = None
    npxg_diff: Optional[float] = None
    ppda: Optional[float] = None
    ppda_allowed: Optional[float] = None
    deep: Optional[int] = None
    deep_allowed: Optional[int] = None
    xpts: Optional[float] = None
    points: Optional[int] = None
    result: Optional[str] = None


class PlayerSeasonDTO(BaseModel):
    external_id: Optional[str] = None
    name: Optional[str] = None
    team_title: Optional[str] = None
    games: Optional[int] = None
    minutes: Optional[int] = None
    goals: Optional[int] = None
    assists: Optional[int] = None
    shots: Optional[int] = None
    key_passes: Optional[int] = None
    xg: Optional[float] = None
    xa: Optional[float] = None
    npg: Optional[int] = None
    npxg: Optional[float] = None
    xg_chain: Optional[float] = None
    xg_buildup: Optional[float] = None
    position: Optional[str] = None
    yellow_cards: Optional[int] = None
    red_cards: Optional[int] = None


class ShotDTO(BaseModel):
    external_id: Optional[str] = None
    match_external_id: Optional[str] = None
    player_external_id: Optional[str] = None
    player_name: Optional[str] = None
    is_home: Optional[bool] = None
    minute: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    xg: Optional[float] = None
    result: Optional[str] = None
    situation: Optional[str] = None
    shot_type: Optional[str] = None
    last_action: Optional[str] = None
    player_assisted: Optional[str] = None


class PlayerMatchDTO(BaseModel):
    match_external_id: Optional[str] = None
    player_external_id: Optional[str] = None
    player_name: Optional[str] = None
    team_external_id: Optional[str] = None
    is_home: Optional[bool] = None
    minutes: Optional[int] = None
    goals: Optional[int] = None
    own_goals: Optional[int] = None
    assists: Optional[int] = None
    shots: Optional[int] = None
    key_passes: Optional[int] = None
    xg: Optional[float] = None
    xa: Optional[float] = None
    npg: Optional[int] = None
    npxg: Optional[float] = None
    xg_chain: Optional[float] = None
    xg_buildup: Optional[float] = None
    position: Optional[str] = None
    yellow_cards: Optional[int] = None
    red_cards: Optional[int] = None


# ---------------------------------------------------------------------------
# Transformers
# ---------------------------------------------------------------------------
def transform_league_matches(raw: list[dict[str, Any]]) -> list[MatchDTO]:
    """Understat ``league.get_match_data`` -> list of :class:`MatchDTO`."""
    matches: list[MatchDTO] = []
    for row in raw or []:
        home = row.get("h") or {}
        away = row.get("a") or {}
        goals = row.get("goals") or {}
        xg = row.get("xG") or {}
        forecast = row.get("forecast") or {}
        matches.append(
            MatchDTO(
                external_id=clean_str(row.get("id")),
                home_external_id=clean_str(home.get("id")),
                home_name=clean_str(home.get("title")),
                away_external_id=clean_str(away.get("id")),
                away_name=clean_str(away.get("title")),
                match_datetime=parse_datetime(row.get("datetime")),
                home_goals=to_int(goals.get("h")),
                away_goals=to_int(goals.get("a")),
                home_xg=to_float(xg.get("h")),
                away_xg=to_float(xg.get("a")),
                forecast_w=to_float(forecast.get("w")),
                forecast_d=to_float(forecast.get("d")),
                forecast_l=to_float(forecast.get("l")),
                is_result=bool(row.get("isResult", False)),
            )
        )
    return matches


def _result_letter(value: Any) -> Optional[str]:
    text = clean_str(value)
    if text is None:
        return None
    return text[0].lower() if text else None


def transform_league_teams(
    raw: dict[str, Any]
) -> tuple[list[TeamSeasonDTO], list[TeamMatchDTO]]:
    """Understat ``league.get_team_data`` -> (standings, per-match team rows).

    The payload is keyed by team id; each team carries a ``history`` list with
    one row per match. We aggregate that history into a season standing and
    also emit every individual match row.
    """
    standings: list[TeamSeasonDTO] = []
    team_matches: list[TeamMatchDTO] = []

    for team in (raw or {}).values():
        team_ext = clean_str(team.get("id"))
        team_name = clean_str(team.get("title"))
        history = team.get("history") or []

        # Sort chronologically so "form" reflects the latest matches.
        dated = [(parse_datetime(h.get("date")), h) for h in history]
        dated.sort(key=lambda t: (t[0] is None, t[0] or datetime.min))

        agg = {
            "mp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0,
            "pts": 0, "xg": 0.0, "xga": 0.0, "npxg": 0.0, "xpts": 0.0, "deep": 0,
        }
        results: list[str] = []

        for match_date, h in dated:
            result = _result_letter(h.get("result"))
            scored = to_int(h.get("scored")) or 0
            missed = to_int(h.get("missed")) or 0
            agg["mp"] += 1
            agg["w"] += to_int(h.get("wins")) or 0
            agg["d"] += to_int(h.get("draws")) or 0
            agg["l"] += to_int(h.get("loses")) or 0
            agg["gf"] += scored
            agg["ga"] += missed
            agg["pts"] += to_int(h.get("pts")) or 0
            agg["xg"] += to_float(h.get("xG")) or 0.0
            agg["xga"] += to_float(h.get("xGA")) or 0.0
            agg["npxg"] += to_float(h.get("npxG")) or 0.0
            agg["xpts"] += to_float(h.get("xpts")) or 0.0
            agg["deep"] += to_int(h.get("deep")) or 0
            if result:
                results.append(result.upper())

            team_matches.append(
                TeamMatchDTO(
                    team_external_id=team_ext,
                    team_name=team_name,
                    match_date=match_date,
                    is_home=to_bool_home(h.get("h_a")),
                    goals=scored,
                    conceded=missed,
                    xg=to_float(h.get("xG")),
                    xga=to_float(h.get("xGA")),
                    npxg=to_float(h.get("npxG")),
                    npxg_diff=to_float(h.get("npxGD")),
                    ppda=normalize_ppda(h.get("ppda")),
                    ppda_allowed=normalize_ppda(h.get("ppda_allowed")),
                    deep=to_int(h.get("deep")),
                    deep_allowed=to_int(h.get("deep_allowed")),
                    xpts=to_float(h.get("xpts")),
                    points=to_int(h.get("pts")),
                    result=result,
                )
            )

        standings.append(
            TeamSeasonDTO(
                team_external_id=team_ext,
                team_name=team_name,
                matches_played=agg["mp"],
                wins=agg["w"],
                draws=agg["d"],
                losses=agg["l"],
                goals_for=agg["gf"],
                goals_against=agg["ga"],
                points=agg["pts"],
                xg=round(agg["xg"], 4),
                xga=round(agg["xga"], 4),
                npxg=round(agg["npxg"], 4),
                xpts=round(agg["xpts"], 4),
                deep=agg["deep"],
                form="".join(results[-5:]) or None,
            )
        )

    return standings, team_matches


def transform_league_players(raw: list[dict[str, Any]]) -> list[PlayerSeasonDTO]:
    """Understat ``league.get_player_data`` -> list of :class:`PlayerSeasonDTO`."""
    players: list[PlayerSeasonDTO] = []
    for row in raw or []:
        players.append(
            PlayerSeasonDTO(
                external_id=clean_str(row.get("id")),
                name=clean_str(row.get("player_name")),
                team_title=clean_str(row.get("team_title")),
                games=to_int(row.get("games")),
                minutes=to_int(row.get("time")),
                goals=to_int(row.get("goals")),
                assists=to_int(row.get("assists")),
                shots=to_int(row.get("shots")),
                key_passes=to_int(row.get("key_passes")),
                xg=to_float(row.get("xG")),
                xa=to_float(row.get("xA")),
                npg=to_int(row.get("npg")),
                npxg=to_float(row.get("npxG")),
                xg_chain=to_float(row.get("xGChain")),
                xg_buildup=to_float(row.get("xGBuildup")),
                position=clean_str(row.get("position")),
                yellow_cards=to_int(row.get("yellow_cards")),
                red_cards=to_int(row.get("red_cards")),
            )
        )
    return players


def transform_match_shots(raw: dict[str, Any]) -> list[ShotDTO]:
    """Understat ``match.get_shot_data`` -> flat list of :class:`ShotDTO`."""
    shots: list[ShotDTO] = []
    for side in ("h", "a"):
        for row in (raw or {}).get(side, []) or []:
            shots.append(
                ShotDTO(
                    external_id=clean_str(row.get("id")),
                    match_external_id=clean_str(row.get("match_id")),
                    player_external_id=clean_str(row.get("player_id")),
                    player_name=clean_str(row.get("player")),
                    is_home=to_bool_home(row.get("h_a")),
                    minute=to_int(row.get("minute")),
                    x=to_float(row.get("X")),
                    y=to_float(row.get("Y")),
                    xg=to_float(row.get("xG")),
                    result=clean_str(row.get("result")),
                    situation=clean_str(row.get("situation")),
                    shot_type=clean_str(row.get("shotType")),
                    last_action=clean_str(row.get("lastAction")),
                    player_assisted=clean_str(row.get("player_assisted")),
                )
            )
    return shots


def transform_roster(raw: dict[str, Any]) -> list[PlayerMatchDTO]:
    """Understat ``match.get_roster_data`` -> list of :class:`PlayerMatchDTO`."""
    rosters: list[PlayerMatchDTO] = []
    for side in ("h", "a"):
        side_players = (raw or {}).get(side, {}) or {}
        is_home = side == "h"
        for row in side_players.values():
            rosters.append(
                PlayerMatchDTO(
                    match_external_id=clean_str(row.get("match_id")),
                    player_external_id=clean_str(row.get("player_id")),
                    player_name=clean_str(row.get("player")),
                    team_external_id=clean_str(row.get("team_id")),
                    is_home=is_home,
                    minutes=to_int(row.get("time")),
                    goals=to_int(row.get("goals")),
                    own_goals=to_int(row.get("own_goals")),
                    assists=to_int(row.get("assists")),
                    shots=to_int(row.get("shots")),
                    key_passes=to_int(row.get("key_passes")),
                    xg=to_float(row.get("xG")),
                    xa=to_float(row.get("xA")),
                    npg=to_int(row.get("npg")),
                    npxg=to_float(row.get("npxG")),
                    xg_chain=to_float(row.get("xGChain")),
                    xg_buildup=to_float(row.get("xGBuildup")),
                    position=clean_str(row.get("position")),
                    yellow_cards=to_int(row.get("yellow_card")),
                    red_cards=to_int(row.get("red_card")),
                )
            )
    return rosters
