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
    _add_column_if_missing("time_entry", "impact", "TEXT NOT NULL DEFAULT 'low'")
    _add_column_if_missing("time_entry", "notes", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing("time_entry", "manual", "INTEGER NOT NULL DEFAULT 0")
    # Comma-joined signal sources ("calendar", "teams", "email", "inferred",
    # "manual"). Surfaces provenance tags in the Briefing UI.
    _add_column_if_missing("time_entry", "sources", "TEXT NOT NULL DEFAULT ''")
    # v0.4: Impact collapsed from 3-tier (high/medium/low) to binary
    # (high/low). Coerce any persisted ``medium`` rows so the UI doesn't
    # render them as an unknown state.
    with _engine.begin() as conn:
        conn.execute(text("UPDATE time_entry SET impact='low' WHERE impact='medium'"))


def get_session() -> Session:
    return Session(_engine)
