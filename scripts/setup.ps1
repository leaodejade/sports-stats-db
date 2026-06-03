# Fresh-machine setup for Windows (PowerShell).
# Usage:  ./scripts/setup.ps1
$ErrorActionPreference = "Stop"

Write-Host "Creating virtual environment (.venv)..."
python -m venv .venv
& .\.venv\Scripts\Activate.ps1

Write-Host "Installing the package (with dev extras)..."
python -m pip install --upgrade pip
pip install -e ".[dev]"

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example"
}

Write-Host "Applying database migrations..."
alembic upgrade head

Write-Host "`nSetup complete. Try:  sports-stats --help"
Write-Host "First data:           sports-stats ingest-understat --league EPL --season 2023"
