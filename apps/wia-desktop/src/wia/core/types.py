"""Pydantic models shared across the app."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Impact(StrEnum):
    """Business-impact tag for a time entry.

    Drives WIA Review's "what to highlight" logic — high-impact items are
    surfaced in talking points and insights, while low-impact items
    (Internal / Admin / the user's own org) are de-emphasized.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Source(StrEnum):
    CALENDAR = "calendar"
    TEAMS = "teams"
    EMAIL = "email"
    INFERRED = "inferred"


class ActivityBlock(BaseModel):
    """A contiguous slice of work time derived from one or more signals."""

    id: int | None = None
    start: datetime
    end: datetime
    title: str | None = None
    participants: list[str] = Field(default_factory=list)
    source: Source
    confidence: Confidence
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def duration_hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0


class TimeEntry(BaseModel):
    id: int | None = None
    label: str
    category: str | None = None
    duration_hours: float
    confidence: Confidence = Confidence.MEDIUM
    impact: Impact = Impact.MEDIUM
    week_of: str | None = None  # ISO date of week start (Monday)
    source_block_ids: list[int] = Field(default_factory=list)
    daily_hours: dict[str, float] = Field(default_factory=dict)
    """Mapping ``YYYY-MM-DD`` -> hours for that day (Mon..Fri)."""
    notes: str = ""
    """Free-text notes attached by the user (visible in Briefing, surfaced in Review)."""
    manual: bool = False
    """True when the user created this entry by hand (no Work IQ source block)."""
    sources: list[str] = Field(default_factory=list)
    """Signal sources that contributed to this entry (e.g. ``calendar``, ``teams``,
    ``email``, ``inferred``, ``manual``). Surfaced as tags in the Briefing UI."""


class TimeEntryUpdate(BaseModel):
    label: str | None = None
    category: str | None = None
    duration_hours: float | None = None
    impact: Impact | None = None
    notes: str | None = None
    daily_hours: dict[str, float] | None = None


class BriefingTotals(BaseModel):
    total_hours: float
    meetings_hours: float
    focus_hours: float
    collaboration_hours: float


class WorkAreaSummary(BaseModel):
    label: str
    hours: float


class Briefing(BaseModel):
    week_start: str  # ISO date (Monday)
    week_end: str  # ISO date (Friday)
    totals: BriefingTotals
    top_work_areas: list[WorkAreaSummary]
    entries: list[TimeEntry]
    blocks: list[ActivityBlock]
    generated_at: datetime
    status: Literal["ok", "no-signals", "workiq-not-enabled"] = "ok"


# ---------------------------------------------------------------------------
# WIA Review — monthly / annual aggregation models
# ---------------------------------------------------------------------------


class CategoryBreakdown(BaseModel):
    """Total hours and % share for a single category over the review period."""

    category: str
    hours: float
    percent: float
    entry_count: int


class TopLabel(BaseModel):
    """A specific activity label aggregated across the review period."""

    label: str
    category: str | None = None
    hours: float
    weeks_active: int
    impact: Impact = Impact.MEDIUM
    notes: list[str] = Field(default_factory=list)
    """User-authored notes from the underlying entries (deduplicated, in order)."""


class WeeklyPoint(BaseModel):
    """One bar in the weekly-trend chart for the review period."""

    week_of: str
    total_hours: float
    meetings_hours: float
    focus_hours: float


class Insight(BaseModel):
    """A single human-readable observation derived from the data."""

    kind: Literal["trend", "highlight", "balance", "anomaly"]
    title: str
    detail: str
    metric: float | None = None  # the underlying delta / ratio that triggered the insight


class TalkingPoint(BaseModel):
    """A bullet point for the 1:1 conversation builder."""

    section: Literal["achievements", "focus", "challenges", "asks"]
    text: str


class ReviewTotals(BaseModel):
    total_hours: float
    meetings_hours: float
    focus_hours: float
    collaboration_hours: float
    meeting_ratio: float  # meetings / total, 0..1
    weeks_observed: int


class ReviewDelta(BaseModel):
    """Change vs. the previous period of the same length."""

    total_hours_delta: float
    meetings_ratio_delta: float
    focus_hours_delta: float


class Review(BaseModel):
    period_kind: Literal["month", "year"]
    period_label: str  # "March 2026" or "2026"
    period_start: str  # ISO date (inclusive)
    period_end: str  # ISO date (inclusive)
    totals: ReviewTotals
    delta: ReviewDelta | None = None
    categories: list[CategoryBreakdown]
    top_labels: list[TopLabel]
    high_impact_labels: list[TopLabel] = Field(default_factory=list)
    weekly_trend: list[WeeklyPoint]
    insights: list[Insight]
    talking_points: list[TalkingPoint]
    generated_at: datetime
    status: Literal["ok", "no-data"] = "ok"
    # Coverage: every Monday whose week intersects the period that has not
    # been scanned yet (no saved entries). Future weeks are excluded so we
    # don't nag users to scan weeks that haven't happened. Used by the UI
    # to surface a "missing data — run scan" prompt.
    missing_weeks: list[str] = Field(default_factory=list)
    # Total number of past-or-current weeks that intersect the period.
    expected_weeks: int = 0
