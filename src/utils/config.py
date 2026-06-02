"""Application configuration loaded from environment / .env file.

All settings have sensible defaults so the project runs out of the box with
SQLite. Paths declared relative are resolved against the project root.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/utils/config.py -> parents[2] == project root
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

_SQLITE_PREFIX = "sqlite:///"


class Settings(BaseSettings):
    """Strongly-typed settings, populated from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(default="sqlite:///data/processed/sports.db")
    raw_data_dir: str = Field(default="data/raw")
    processed_data_dir: str = Field(default="data/processed")
    log_level: str = Field(default="INFO")
    understat_request_delay: float = Field(default=2.0)
    cache_enabled: bool = Field(default=True)

    # -- derived paths ------------------------------------------------------
    def _resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def raw_path(self) -> Path:
        return self._resolve(self.raw_data_dir)

    @property
    def processed_path(self) -> Path:
        return self._resolve(self.processed_data_dir)

    @property
    def resolved_database_url(self) -> str:
        """Return a database URL with relative SQLite paths made absolute.

        Ensures the parent directory of a SQLite file exists so the engine can
        be created without manual setup.
        """
        if self.database_url.startswith(_SQLITE_PREFIX):
            raw = self.database_url[len(_SQLITE_PREFIX):]
            db_path = Path(raw)
            if not db_path.is_absolute():
                db_path = PROJECT_ROOT / db_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            return f"{_SQLITE_PREFIX}{db_path.as_posix()}"
        return self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance and ensure data directories exist."""
    settings = Settings()
    settings.raw_path.mkdir(parents=True, exist_ok=True)
    settings.processed_path.mkdir(parents=True, exist_ok=True)
    return settings
