"""SQLModel definitions for persisted state."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class ActivityBlockRow(SQLModel, table=True):
    __tablename__ = "activity_block"

    id: int | None = Field(default=None, primary_key=True)
    start: datetime
    end: datetime
    title: str | None = None
    participants: str = ""  # comma-joined emails
    source: str
    confidence: str
    week_of: str = Field(index=True)


class TimeEntryRow(SQLModel, table=True):
    __tablename__ = "time_entry"

    id: int | None = Field(default=None, primary_key=True)
    label: str
    category: str | None = None
    duration_hours: float
    confidence: str
    week_of: str = Field(index=True)
    source_block_ids: str = ""  # comma-joined ints
    user_edited: bool = False
    daily_hours: str = ""  # JSON-encoded dict[str, float]
    impact: str = "medium"  # "high" | "medium" | "low"


class UserPref(SQLModel, table=True):
    __tablename__ = "user_pref"

    key: str = Field(primary_key=True)
    value: str


class ScanHistoryRow(SQLModel, table=True):
    """One row per Work IQ scan attempt (manual or scheduled).

    Persists what week the scan covered, who triggered it, the resulting
    status, and how many entries the briefing produced. Used to render the
    Scan history UI panel and to audit what the app did in the background.
    """

    __tablename__ = "scan_history"

    id: int | None = Field(default=None, primary_key=True)
    ran_at: datetime = Field(index=True)
    week_of: str = Field(index=True)  # ISO Monday of the scanned week
    trigger: str  # "manual" | "scheduled"
    status: str  # briefing.status, or "error: ..." on failure
    entry_count: int = 0
    duration_ms: int = 0
