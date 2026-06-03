# ADR-0001: Finalize sports-stats-db as a v1.0 installable modular monolith

**Status:** Accepted
**Date:** 2026-06-03
**Deciders:** project owner (leaodejade)

## Context

`sports-stats-db` is the **data layer** of a personal sports-betting workflow:
an external step uses Codex to OCR bookmaker odds from screenshots, a separate
model does the maths, and this repository must store everything *correctly* so a
wrong number never produces a wrong bet slip. Betting is **pre-match only**
(no live/in-play).

The codebase already has: a layered pipeline (collectors → transformers →
services → analysis/features/backtest), Alembic migrations, an OCR validation
gate, a leakage-free feature store, a backtest/calibration engine, a bet-slip
pre-flight gate, and 93 network-free tests.

Forces at play:
- It must be **portable** — set up and run on another computer from a clean
  clone with minimal steps.
- It must stay **simple to operate** (single user, modest data volume since odds
  are captured a few times per match, not streamed).
- It must remain **trustworthy** (validated data, reproducible schema, tested).

## Decision

Ship v1.0 as an **installable Python package (modular monolith)**:
- `pyproject.toml` with a `sports-stats` console entry point; CLI moved into the
  package (`src/cli.py`), `main.py` kept as a thin shim.
- **SQLite by default, PostgreSQL opt-in** via `DATABASE_URL` (no code change).
- **Alembic is the single source of truth** for the schema; `init-db`
  (`create_all`) remains for quick dev/tests.
- Three stable consumption interfaces for the external scraper/model: **import
  the package**, **CLI commands**, or **JSON ingestion** (language-agnostic).
- **GitHub Actions CI** runs migrations + tests on 3.11/3.12 to guarantee a
  clean-machine build.
- One-command setup scripts (`scripts/setup.ps1`, `scripts/setup.sh`, `make
  setup`).

## Options Considered

### Option A: Installable modular monolith (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Cost | Free (SQLite; Postgres only if needed) |
| Scalability | Ample for pre-match volumes; Postgres path exists |
| Team familiarity | High (plain Python/SQLAlchemy/Typer) |

**Pros:** trivial to install/run elsewhere; clear module boundaries; one process
to reason about; fast tests; easy to back up (one DB file).
**Cons:** not horizontally scalable (irrelevant here); `src`-named package is a
minor naming quirk.

### Option B: Split into services (collector / API / model-store)
| Dimension | Assessment |
|-----------|------------|
| Complexity | High |
| Cost | Higher (multiple processes, infra) |
| Scalability | High (unneeded) |
| Team familiarity | Medium |

**Pros:** independent scaling/deploys.
**Cons:** massive over-engineering for a single-user, pre-match workload;
operational burden; slower iteration. Rejected.

### Option C: Keep ad-hoc scripts + notebooks (status quo before v1)
**Pros:** zero packaging work.
**Cons:** not portable, no entry point, easy to run the wrong thing, no
reproducible setup. Rejected.

## Trade-off Analysis

The dominant constraints are **portability** and **trust**, not scale. A modular
monolith maximizes both at the lowest complexity: a clean clone + one script
yields a working CLI and a reproducible schema, and the layered boundaries keep
the validation gate / leakage guarantees intact. PostgreSQL is kept one env-var
away so scale is *possible* without paying for it now.

## Consequences

- **Easier:** install on a new machine (`./scripts/setup.ps1`), run via
  `sports-stats`, reproduce the schema (`alembic upgrade head`), trust the build
  (CI), and consume from any language (JSON ingestion).
- **Harder / deferred:** no real-time odds streaming (out of scope — pre-match
  only); horizontal scaling would need a redesign (not anticipated).
- **Revisit when:** odds volume grows to millions of rows or concurrent writers
  appear → migrate to PostgreSQL + TimescaleDB and consider odds store-on-change.

## Action Items

1. [x] Add `pyproject.toml` + `sports-stats` entry point; move CLI to `src/cli.py`.
2. [x] Consolidate config into `pyproject.toml` (remove `pytest.ini`).
3. [x] Add GitHub Actions CI (migrations + tests, 3.11/3.12).
4. [x] Add one-command setup scripts (PowerShell/bash) + `Makefile`.
5. [x] Document fresh-machine setup and the corporate-TLS workaround in README.
6. [ ] Tag release `v1.0.0` after merge.
7. [ ] (Future) PostgreSQL/TimescaleDB + calibration-drift monitoring when scale demands.
