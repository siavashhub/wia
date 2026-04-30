"""Application configuration and paths."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from platformdirs import PlatformDirs
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_dirs = PlatformDirs(appname="WIA", appauthor="WIA", roaming=False)


class Settings(BaseSettings):
    """Runtime settings.

    Environment variables prefixed with ``WIA_`` override defaults.
    """

    model_config = SettingsConfigDict(env_prefix="WIA_", env_file=".env", extra="ignore")

    # Work IQ launch — MCP server mode of the @microsoft/workiq npm package.
    # The CLI handles M365 authentication itself (first-party Entra app +
    # tenant admin consent). No app registration required from WIA.
    workiq_command: str = "npx"
    workiq_args: list[str] = Field(default_factory=lambda: ["-y", "@microsoft/workiq", "mcp"])
    # Used to verify Work IQ is installed (and trigger first-run auth on demand).
    workiq_cli_args: list[str] = Field(default_factory=lambda: ["-y", "@microsoft/workiq"])

    # UI
    window_title: str = "WIA — Work Intelligence Agent"
    window_width: int = 1200
    window_height: int = 800

    # Logging
    log_level: str = "INFO"

    # Optional override for the user data directory. When set (typically via
    # the ``WIA_DATA_DIR`` environment variable), the SQLite database and
    # other persistent state live here instead of the OS default. This is
    # what tests and CI use to keep fixture data off the real user DB.
    data_dir_override: Path | None = Field(default=None, validation_alias="WIA_DATA_DIR")

    @property
    def data_dir(self) -> Path:
        p = self.data_dir_override or Path(_dirs.user_data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cache_dir(self) -> Path:
        p = Path(_dirs.user_cache_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wia.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
