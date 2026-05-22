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
    impact: str = "low"  # "high" | "low"
    notes: str = ""  # free-text notes the user attaches in WIA Briefing
    manual: bool = False  # entry was created by the user (no Work IQ source)
    sources: str = ""  # comma-joined signal sources (calendar/teams/email/inferred/manual)


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


class ActionRow(SQLModel, table=True):
    """A WIA Actions suggestion persisted across rescans.

    ``dedupe_key`` is the stable identity of a suggestion — orchestrator
    rescans upsert by this key so a re-scan never produces duplicate
    rows for the same underlying signal. Status changes (accept /
    snooze / dismiss / complete) are stored in-place; ``dismissed``
    rows are kept so future scans can suppress them as a learning
    signal.
    """

    __tablename__ = "action"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime
    updated_at: datetime
    week_of: str = Field(index=True)
    kind: str  # ActionKind value
    title: str
    rationale: str
    source_entry_id: int | None = Field(default=None, index=True)
    dedupe_key: str = Field(index=True, unique=True)
    payload: str = ""  # JSON-encoded dict
    status: str = "suggested"  # ActionStatus value
    priority: int = 50
    snoozed_until: datetime | None = None
    completed_at: datetime | None = None
    dismissed_reason: str | None = None
