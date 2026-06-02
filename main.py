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

from src.analysis import football as fb
from src.analysis import data_quality as dq
from src.collectors import UnderstatCollector
from src.collectors.tennis_sackmann_collector import TennisSackmannCollector
from src.database import get_engine, init_db, session_scope
from src.services import IngestionService
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


if __name__ == "__main__":
    app()
