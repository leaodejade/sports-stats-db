"""Command-line interface for the sports stats database.

Examples
--------
    python main.py init-db
    python main.py ingest-understat --league EPL --season 2023
    python main.py team-stats --team "Arsenal" --season 2023
    python main.py player-stats --player "Erling Haaland"
    python main.py xg-table --league EPL --season 2023
"""

from __future__ import annotations

import pandas as pd
import typer

import json
from pathlib import Path

from src.analysis import betting as ab
from src.analysis import calibration as cal
from src.analysis import data_quality as dq
from src.analysis import football as fb
from src.backtest import BacktestConfig, run_backtest, summarize_by
from src.collectors import UnderstatCollector
from src.collectors.tennis_sackmann_collector import TennisSackmannCollector
from src.collectors.understat_collector import UNDERSTAT_LEAGUES
from src.database import get_engine, init_db, session_scope
from src.services import IngestionService
from src.services.bootstrap import bootstrap as run_bootstrap
from src.services import bet_slip as bs
from src.services import json_ingest as ji
from src.services import odds_ingest as oi
from src.services.tennis_ingestion import TennisIngestionService
from src.utils import get_settings, setup_logging

app = typer.Typer(
    add_completion=False,
    help="Local football (Understat) statistics database — tennis-ready.",
)


def _echo_df(df: pd.DataFrame, empty_message: str = "No data found.") -> None:
    """Pretty-print a DataFrame, or a friendly message when empty."""
    if df is None or df.empty:
        typer.secho(empty_message, fg=typer.colors.YELLOW)
        return
    with pd.option_context("display.max_rows", None, "display.width", None):
        typer.echo(df.to_string(index=False))


@app.command("init-db")
def init_db_command() -> None:
    """Create all tables and seed reference data."""
    setup_logging(get_settings().log_level)
    init_db()
    typer.secho("Database initialised.", fg=typer.colors.GREEN)


@app.command("bootstrap")
def bootstrap_command(
    leagues: str = typer.Option(
        "EPL", "--leagues", help="Comma-separated league codes, or 'all' for the 6 Understat leagues."
    ),
    season_from: int = typer.Option(2021, "--from", help="First season start year."),
    season_to: int = typer.Option(2023, "--to", help="Last season start year (inclusive)."),
    features: bool = typer.Option(
        True, "--features/--no-features", help="Build pre-match features after ingesting."
    ),
    with_shots: bool = typer.Option(
        False, "--with-shots", help="Also fetch per-match shots & rosters (slow)."
    ),
    no_cache: bool = typer.Option(False, "--no-cache", help="Ignore cached raw JSON."),
) -> None:
    """One-shot setup: ingest many leagues x seasons (+ features). Ideal on a new machine.

    Examples:
        sports-stats bootstrap                         # EPL 2021-2023 + features
        sports-stats bootstrap --leagues all --from 2019 --to 2023
    """
    setup_logging(get_settings().log_level)
    codes = list(UNDERSTAT_LEAGUES) if leagues.strip().lower() == "all" else [
        c.strip() for c in leagues.split(",") if c.strip()
    ]
    seasons = [str(y) for y in range(season_from, season_to + 1)]
    typer.secho(
        f"Bootstrapping {len(codes)} league(s) x {len(seasons)} season(s)...",
        fg=typer.colors.CYAN,
    )
    collector = UnderstatCollector(cache_enabled=not no_cache)
    report = run_bootstrap(
        collector=collector, engine=get_engine(), leagues=codes, seasons=seasons,
        with_features=features, with_shots=with_shots,
    )
    summary = report.as_dict()
    color = typer.colors.GREEN if summary["failed"] == 0 else typer.colors.YELLOW
    typer.secho(
        f"Done: {summary['ingested']} ingested, {summary['failed']} failed, "
        f"{summary['features_built']} feature rows built.",
        fg=color,
    )
    for league, season, err in report.failures:
        typer.secho(f"  FAILED {league} {season}: {err}", fg=typer.colors.RED)


@app.command("ingest-understat")
def ingest_understat_command(
    league: str = typer.Option(..., "--league", "-l", help="Understat league code, e.g. EPL"),
    season: str = typer.Option(..., "--season", "-s", help="Season start year, e.g. 2023"),
    with_shots: bool = typer.Option(
        False, "--with-shots", help="Also fetch per-match shots & rosters (slow)."
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Ignore cached raw JSON and refetch."
    ),
) -> None:
    """Collect and store one league+season from Understat."""
    settings = get_settings()
    setup_logging(settings.log_level)
    init_db()  # ensure schema exists

    collector = UnderstatCollector(cache_enabled=not no_cache)
    service = IngestionService(collector=collector, engine=get_engine())
    result = service.ingest_understat(league=league, season=season, with_shots=with_shots)

    typer.secho(
        f"[{result.status}] {league} {season} in {result.duration_seconds:.1f}s",
        fg=typer.colors.GREEN if result.status == "success" else typer.colors.RED,
    )
    for key, value in sorted(result.counts.items()):
        typer.echo(f"  {key}: {value}")


@app.command("ingest-tennis")
def ingest_tennis_command(
    tour: str = typer.Option(..., "--tour", help="Tennis tour: ATP or WTA"),
    season: str = typer.Option(..., "--season", help="Season year, e.g. 2023"),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Ignore cached raw JSON and refetch."
    ),
) -> None:
    """Collect and store one tour+season of tennis data from Jeff Sackmann."""
    settings = get_settings()
    setup_logging(settings.log_level)
    init_db()  # ensure schema exists

    collector = TennisSackmannCollector(cache_enabled=not no_cache)
    service = TennisIngestionService(collector=collector, engine=get_engine())
    result = service.ingest_tennis(tour=tour, season=season)

    typer.secho(
        f"[{result.status}] {tour} {season} in {result.duration_seconds:.1f}s",
        fg=typer.colors.GREEN if result.status == "success" else typer.colors.RED,
    )
    for key, value in sorted(result.counts.items()):
        typer.echo(f"  {key}: {value}")


@app.command("team-stats")
def team_stats_command(
    team: str = typer.Option(..., "--team", "-t", help="Team name (partial match)."),
    season: str = typer.Option(..., "--season", "-s", help="Season start year."),
) -> None:
    """Show a team's season summary (record, xG, xGA, form)."""
    setup_logging(get_settings().log_level)
    with session_scope(get_engine()) as session:
        df = fb.team_season_stats(session, team=team, season=season)
        _echo_df(df, f"No standing found for '{team}' in season {season}.")


@app.command("player-stats")
def player_stats_command(
    player: str = typer.Option(..., "--player", "-p", help="Player name (partial match)."),
) -> None:
    """Show a player's season-by-season stat lines."""
    setup_logging(get_settings().log_level)
    with session_scope(get_engine()) as session:
        df = fb.player_stats(session, player=player)
        _echo_df(df, f"No player matching '{player}'.")


@app.command("xg-table")
def xg_table_command(
    league: str = typer.Option(..., "--league", "-l", help="Understat league code."),
    season: str = typer.Option(..., "--season", "-s", help="Season start year."),
) -> None:
    """Print the full season table with real and expected metrics."""
    setup_logging(get_settings().log_level)
    with session_scope(get_engine()) as session:
        df = fb.xg_table(session, league=league, season=season)
        _echo_df(df, f"No data for {league} {season}. Did you ingest it?")


@app.command("team-xg")
def team_xg_command(
    league: str = typer.Option(..., "--league", "-l"),
    season: str = typer.Option(..., "--season", "-s"),
    metric: str = typer.Option("xg", "--metric", help="xg | xga | diff"),
) -> None:
    """Rank teams by xG, xGA, or xG balance."""
    setup_logging(get_settings().log_level)
    funcs = {
        "xg": fb.team_xg_ranking,
        "xga": fb.team_xga_ranking,
        "diff": fb.team_xg_diff,
    }
    func = funcs.get(metric)
    if func is None:
        typer.secho("metric must be one of: xg, xga, diff", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    with session_scope(get_engine()) as session:
        _echo_df(func(session, league=league, season=season))


@app.command("top-players")
def top_players_command(
    metric: str = typer.Option("xg", "--metric", help="xg | xa | over | under"),
    league: str = typer.Option(None, "--league", "-l"),
    season: str = typer.Option(None, "--season", "-s"),
    limit: int = typer.Option(15, "--limit", "-n"),
    min_minutes: int = typer.Option(
        450, "--min-minutes", help="Minutes filter for over/under-performance."
    ),
) -> None:
    """Top players by xG / xA, or over/under-performers (goals vs xG)."""
    setup_logging(get_settings().log_level)
    with session_scope(get_engine()) as session:
        if metric == "xg":
            df = fb.top_players_by_xg(session, league=league, season=season, limit=limit)
        elif metric == "xa":
            df = fb.top_players_by_xa(session, league=league, season=season, limit=limit)
        elif metric == "over":
            df = fb.player_overperformers(
                session, league=league, season=season, limit=limit,
                min_minutes=min_minutes,
            )
        elif metric == "under":
            df = fb.player_underperformers(
                session, league=league, season=season, limit=limit,
                min_minutes=min_minutes,
            )
        else:
            typer.secho("metric must be one of: xg, xa, over, under", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        _echo_df(df)


@app.command("form")
def form_command(
    team: str = typer.Option(..., "--team", "-t"),
    season: str = typer.Option(..., "--season", "-s"),
    n: int = typer.Option(5, "--n", help="Number of recent matches."),
) -> None:
    """Show a team's recent form (last N matches)."""
    setup_logging(get_settings().log_level)
    with session_scope(get_engine()) as session:
        _echo_df(fb.recent_form(session, team=team, season=season, n=n))


@app.command("real-vs-expected")
def real_vs_expected_command(
    league: str = typer.Option(..., "--league", "-l"),
    season: str = typer.Option(..., "--season", "-s"),
) -> None:
    """Compare actual points/goals against xPTS / xG for every team."""
    setup_logging(get_settings().log_level)
    with session_scope(get_engine()) as session:
        _echo_df(fb.real_vs_expected(session, league=league, season=season))


@app.command("validate")
def validate_command(
    league: str = typer.Option(None, "--league", "-l"),
    season: str = typer.Option(None, "--season", "-s"),
) -> None:
    """Run data quality validations and print violations."""
    setup_logging(get_settings().log_level)
    with session_scope(get_engine()) as session:
        df = dq.run_all_validations(session)
        if df.empty:
            typer.secho("No violations found. Data quality is good!", fg=typer.colors.GREEN)
        else:
            typer.secho(f"Found {len(df)} violations:", fg=typer.colors.RED)
            _echo_df(df)


# ---------------------------------------------------------------------------
# Betting data layer: JSON ingestion (for an external odds/model system)
# ---------------------------------------------------------------------------
def _load_json(file: str) -> list:
    data = json.loads(Path(file).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else [data]


def _load_json_obj(file: str) -> dict:
    return json.loads(Path(file).read_text(encoding="utf-8"))


@app.command("ingest-odds-json")
def ingest_odds_json_command(
    file: str = typer.Option(..., "--file", "-f", help="JSON file of fixtures+odds."),
) -> None:
    """Load bookmaker odds from a JSON payload into the database."""
    setup_logging(get_settings().log_level)
    init_db()
    with session_scope(get_engine()) as session:
        counts = ji.ingest_odds_payload(session, _load_json(file))
    typer.secho(f"Ingested odds: {counts}", fg=typer.colors.GREEN)


@app.command("ingest-odds-capture")
def ingest_odds_capture_command(
    file: str = typer.Option(..., "--file", "-f", help="JSON capture from OCR/screenshots."),
    min_confidence: float = typer.Option(
        0.0, "--min-confidence", help="Reject captures below this OCR confidence."
    ),
    no_promote: bool = typer.Option(
        False, "--no-promote", help="Only stage+validate; do not promote."
    ),
) -> None:
    """Gated ingestion of OCR odds: stage -> validate -> promote to odds tables."""
    setup_logging(get_settings().log_level)
    init_db()
    with session_scope(get_engine()) as session:
        report = oi.ingest_capture(
            session, _load_json_obj(file), min_confidence=min_confidence,
            promote=not no_promote,
        )
    color = typer.colors.GREEN if report["rejected"] == 0 else typer.colors.YELLOW
    typer.secho(f"Capture report: {report}", fg=color)


@app.command("ingest-prediction-json")
def ingest_prediction_json_command(
    file: str = typer.Option(..., "--file", "-f", help="JSON file of model predictions."),
) -> None:
    """Load model predictions from a JSON payload into the database."""
    setup_logging(get_settings().log_level)
    init_db()
    with session_scope(get_engine()) as session:
        counts = ji.ingest_predictions_payload(session, _load_json(file))
    typer.secho(f"Ingested predictions: {counts}", fg=typer.colors.GREEN)


@app.command("ingest-results-json")
def ingest_results_json_command(
    file: str = typer.Option(..., "--file", "-f", help="JSON file of market results."),
) -> None:
    """Load settled market results from a JSON payload into the database."""
    setup_logging(get_settings().log_level)
    init_db()
    with session_scope(get_engine()) as session:
        counts = ji.ingest_results_payload(session, _load_json(file))
    typer.secho(f"Ingested results: {counts}", fg=typer.colors.GREEN)


# ---------------------------------------------------------------------------
# Betting data layer: reporting
# ---------------------------------------------------------------------------
@app.command("build-slip")
def build_slip_command(
    file: str = typer.Option(..., "--file", "-f", help="JSON slip spec (legs, stake...)."),
    require_gate: bool = typer.Option(
        True, "--require-gate/--no-require-gate",
        help="Only use odds that passed the OCR validation gate.",
    ),
    min_edge: float = typer.Option(None, "--min-edge", help="Min model edge per leg."),
) -> None:
    """Build a bet slip behind the pre-flight gate (refuses if any leg fails)."""
    setup_logging(get_settings().log_level)
    spec = _load_json_obj(file)
    with session_scope(get_engine()) as session:
        slip = bs.build_bet_slip(
            session,
            legs=spec["legs"], stake=spec.get("stake", 0.0),
            kind=spec.get("kind", "multi"), label=spec.get("label", "slip"),
            model_name=spec.get("model_name"), model_version=spec.get("model_version"),
            require_gate=require_gate,
            min_edge=spec.get("min_edge", min_edge),
            freshness_seconds=spec.get("freshness_seconds"),
        )
        from src.models import BetSlipLeg
        from sqlalchemy import select as _select
        legs = session.scalars(
            _select(BetSlipLeg).where(BetSlipLeg.slip_id == slip.id)
        ).all()
        color = typer.colors.GREEN if slip.status == "ready" else typer.colors.RED
        typer.secho(
            f"Slip #{slip.id} [{slip.status}] odd={slip.combined_odd} ev={slip.ev}",
            fg=color,
        )
        for leg in legs:
            mark = "OK " if leg.status == "ok" else "REJ"
            typer.echo(f"  {mark} match={leg.match_id} {leg.selection} "
                       f"odd={leg.odd} {leg.reason or ''}")


@app.command("backtest")
def backtest_command(
    model: str = typer.Option(..., "--model", "-m", help="model_name to backtest."),
    version: str = typer.Option(None, "--version", help="model_version (optional)."),
    league: str = typer.Option(None, "--league", "-l"),
    threshold: float = typer.Option(0.0, "--threshold", "-t", help="min EV to bet."),
    price: str = typer.Option("best", "--price", help="best | closing"),
) -> None:
    """Value-betting backtest over stored predictions, odds and results."""
    setup_logging(get_settings().log_level)
    cfg = BacktestConfig(model_name=model, model_version=version, league=league,
                         threshold=threshold, price=price)
    with session_scope(get_engine()) as session:
        res = run_backtest(session, cfg)
    typer.secho(f"Summary: {res.summary}", fg=typer.colors.CYAN)
    for dim in ("league", "market", "odd_bucket"):
        typer.secho(f"\nBy {dim}:", fg=typer.colors.CYAN)
        _echo_df(summarize_by(res.bets, dim))


@app.command("calibrate")
def calibrate_command(
    model: str = typer.Option(..., "--model", "-m"),
    version: str = typer.Option(None, "--version"),
    by: str = typer.Option(None, "--by", help="league | market (optional slice)."),
) -> None:
    """Probability calibration (Brier, log-loss, reliability table)."""
    setup_logging(get_settings().log_level)
    with session_scope(get_engine()) as session:
        typer.secho(f"Overall: {cal.calibration_summary(session, model, version)}",
                    fg=typer.colors.CYAN)
        df = cal.prediction_outcomes(session, model, version)
        _echo_df(cal.calibration_table(df), "No settled predictions yet.")
        if by:
            typer.secho(f"\nBy {by}:", fg=typer.colors.CYAN)
            _echo_df(cal.calibration_by(session, by, model, version))


@app.command("clv")
def clv_command() -> None:
    """Closing Line Value of recorded simulated bets."""
    setup_logging(get_settings().log_level)
    with session_scope(get_engine()) as session:
        typer.secho(f"CLV summary: {ab.clv_summary(session)}", fg=typer.colors.CYAN)
        _echo_df(ab.clv_report(session), "No bets with a closing price yet.")


@app.command("pnl")
def pnl_command() -> None:
    """Profit & loss over settled simulated bets (ROI, hit rate, drawdown)."""
    setup_logging(get_settings().log_level)
    with session_scope(get_engine()) as session:
        typer.secho(f"P&L: {ab.pnl_summary(session)}", fg=typer.colors.CYAN)
        _echo_df(ab.bankroll_curve(session), "No bankroll movements yet.")


@app.command("best-odds")
def best_odds_command(
    match: int = typer.Option(None, "--match", help="Filter by match id."),
) -> None:
    """Best available price per match/market/selection across bookmakers."""
    setup_logging(get_settings().log_level)
    with session_scope(get_engine()) as session:
        _echo_df(ab.best_odds(session, match_id=match), "No odds stored yet.")


if __name__ == "__main__":
    app()
