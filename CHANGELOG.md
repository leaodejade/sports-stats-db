# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/);
the project uses [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-06-03

### Added
- `sports-stats bootstrap` — one-shot ingestion of many leagues × seasons that
  also builds the pre-match feature store. Resilient (per-pair failures are
  recorded and skipped). Ideal for setting up a fresh machine.

## [1.0.0] - 2026-06-03

First portable, finalized release.

### Added
- **Installable package** (`pyproject.toml`) with the `sports-stats` console
  entry point; CLI lives in `src/cli.py` (`main.py` is a thin shim).
- **One-command setup**: `scripts/setup.ps1`, `scripts/setup.sh`, `make setup`.
- **GitHub Actions CI** definition (`docs/ci/github-actions-ci.yml`).
- **Betting data layer**: bookmakers, markets, odds snapshots (time-series),
  current odds, market results, versioned predictions, simulated bets, bankroll.
- **Gated OCR-odds ingestion** (`odds_ingest_raw` staging → validate → promote):
  rejects unresolved teams, implausible odds, incomplete markets, bad overround,
  cross-bookmaker outliers, and post-kickoff captures.
- **Leakage-free pre-match feature store** + a leakage-guard test.
- **Backtest + calibration engine** (ROI/PnL/drawdown by league/market/odd
  bucket; Brier/log-loss) with a decision audit trail.
- **Bet-slip pre-flight gate** — emits a slip only if every leg is validated,
  fresh, pre-kickoff and (optionally) shows model edge.
- **Model-honesty hardening**: pre-kickoff-only backtest pricing, de-vig, a
  deterministic closing line, a settlement validator, and CHECK constraints.
- **JSON ingestion adapters** + reporting CLI (`backtest`, `calibrate`, `clv`,
  `pnl`, `best-odds`, `validate`).
- Tennis schema + collector, PostgreSQL support, Alembic migrations,
  data-quality validation, timezone-aware datetimes.

### Notes
- Football odds are bookmaker-sourced (pre-match); `matches.forecast_*` is a
  post-match retrodiction and must not be used as a feature (enforced by docs
  and tests).
