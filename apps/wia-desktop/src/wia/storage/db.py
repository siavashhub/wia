"""SQLite engine + session factory."""

from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from wia.config import get_settings

_settings = get_settings()
_engine = create_engine(f"sqlite:///{_settings.db_path}", echo=False)


def _add_column_if_missing(table: str, column: str, ddl_type: str) -> None:
    """Idempotent ``ALTER TABLE`` for SQLite. No-op if column already exists."""
    with _engine.begin() as conn:
        cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]
        if column not in cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


def init_db() -> None:
    # Import models so SQLModel.metadata is populated.
    from wia.storage import models  # noqa: F401

    SQLModel.metadata.create_all(_engine)
    # Lightweight migrations for columns added after first release.
    _add_column_if_missing("time_entry", "daily_hours", "TEXT NOT NULL DEFAULT ''")


def get_session() -> Session:
    return Session(_engine)
