#!/usr/bin/env bash
# Fresh-machine setup for Linux/macOS.
# Usage:  bash scripts/setup.sh
set -euo pipefail

echo "Creating virtual environment (.venv)..."
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "Installing the package (with dev extras)..."
python -m pip install --upgrade pip
pip install -e ".[dev]"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Applying database migrations..."
alembic upgrade head

echo
echo "Setup complete. Try:  sports-stats --help"
echo "First data:           sports-stats ingest-understat --league EPL --season 2023"
