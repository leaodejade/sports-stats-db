.PHONY: setup test migrate clean

setup:        ## Create venv, install package, apply migrations
	bash scripts/setup.sh

test:         ## Run the test suite
	pytest

migrate:      ## Apply database migrations to head
	alembic upgrade head

clean:        ## Remove venv, caches and build artifacts
	rm -rf .venv .pytest_cache .mypy_cache *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
