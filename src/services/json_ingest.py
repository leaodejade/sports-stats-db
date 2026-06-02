"""Ingest odds / predictions / results from a JSON payload.

Lets an EXTERNAL system (even in another language) feed this database without
importing the Python package: it writes a documented JSON structure and either
calls these functions or pipes the file through the CLI.

Each fixture is identified by (home, away, league, season); ``resolve_match``
creates teams/match if needed and is idempotent.

Payload shapes
--------------
odds::      [{"home","away","league","season","kickoff"?,
              "odds":[{"bookmaker","market","selection","odd","line"?,
                       "is_opening"?,"is_closing"?,"captured_at"?,"source_url"?}]}]
predictions:[{"home","away","league","season","model_name","model_version",
              "predictions":[{"market","selection","probability","line"?}]}]
results::   [{"home","away","league","season",
              "results":[{"market","selection","outcome","line"?,"result_value"?}]}]
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from ..transformers import MarketResultDTO, OddsDTO, PredictionDTO
from ..transformers.base import parse_datetime
from . import betting_repository as br


def _resolve(session: Session, fx: dict[str, Any]) -> int:
    return br.resolve_match(
        session,
        home=fx["home"],
        away=fx["away"],
        league_code=fx["league"],
        season=str(fx["season"]),
        kickoff=parse_datetime(fx.get("kickoff")),
    )


def ingest_odds_payload(session: Session, payload: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for fx in payload or []:
        match_id = _resolve(session, fx)
        for o in fx.get("odds", []):
            dto = OddsDTO(
                bookmaker=o["bookmaker"], market=o["market"],
                selection=o["selection"], odd=float(o["odd"]),
                line=o.get("line"),
                is_opening=bool(o.get("is_opening", False)),
                is_closing=bool(o.get("is_closing", False)),
                captured_at=parse_datetime(o.get("captured_at")),
                source_url=o.get("source_url"),
            )
            br.record_odds(session, match_id, dto)
            counts["odds"] += 1
        counts["fixtures"] += 1
    return dict(counts)


def ingest_predictions_payload(session: Session, payload: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for fx in payload or []:
        match_id = _resolve(session, fx)
        for p in fx.get("predictions", []):
            dto = PredictionDTO(
                model_name=fx["model_name"], model_version=str(fx["model_version"]),
                market=p["market"], selection=p["selection"],
                probability=float(p["probability"]), line=p.get("line"),
                predicted_at=parse_datetime(p.get("predicted_at")),
                extra=p.get("extra"),
            )
            br.record_prediction(session, match_id, dto)
            counts["predictions"] += 1
        counts["fixtures"] += 1
    return dict(counts)


def ingest_results_payload(session: Session, payload: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for fx in payload or []:
        match_id = _resolve(session, fx)
        for r in fx.get("results", []):
            dto = MarketResultDTO(
                market=r["market"], selection=r["selection"],
                outcome=r["outcome"], line=r.get("line"),
                result_value=r.get("result_value"),
                settled_at=parse_datetime(r.get("settled_at")),
            )
            br.upsert_market_result(session, match_id, dto)
            counts["results"] += 1
        counts["fixtures"] += 1
    return dict(counts)
