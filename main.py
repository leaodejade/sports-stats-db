"""Convenience entry point so ``python main.py ...`` keeps working.

The real CLI lives in :mod:`src.cli` (also exposed as the ``sports-stats``
console command after ``pip install``).
"""

from src.cli import app

if __name__ == "__main__":
    app()
