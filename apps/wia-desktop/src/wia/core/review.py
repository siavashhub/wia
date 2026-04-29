"""WIA Review — monthly and annual aggregation over saved time entries.

This module is intentionally deterministic: it derives all numbers and
insights from the rows produced by WIA Briefing, with no external API or
LLM calls. The output is a :class:`Review` bundle that the UI / export
layer can render or hand to a chat surface for narrative refinement.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from wia.core.types import (
    CategoryBreakdown,
    Insight,
    Review,
    ReviewDelta,
    ReviewTotals,
    TalkingPoint,
    TimeEntry,
    TopLabel,
    WeeklyPoint,
)
from wia.storage import entries as entries_repo

# --- public entry points ---------------------------------------------------


def build_monthly_review(year: int, month: int) -> Review:
    start, end = _month_bounds(year, month)
    label = f"{calendar.month_name[month]} {year}"
    return _build_review("month", label, start, end)


def build_yearly_review(year: int) -> Review:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    return _build_review("year", str(year), start, end)


def parse_period(period: str) -> tuple[str, int, int | None]:
    """Parse an API ``period`` string.

    Accepts ``YYYY`` (year) or ``YYYY-MM`` (month). Returns
    ``(kind, year, month_or_None)``.
    """
    period = period.strip()
    if len(period) == 4 and period.isdigit():
        return "year", int(period), None
    if len(period) == 7 and period[4] == "-":
        year_s, month_s = period.split("-", 1)
        if year_s.isdigit() and month_s.isdigit():
            month = int(month_s)
            if 1 <= month <= 12:
                return "month", int(year_s), month
    raise ValueError(f"Invalid period {period!r}; expected YYYY or YYYY-MM")


# --- core builder ----------------------------------------------------------


@dataclass
class _Range:
    start: date
    end: date  # inclusive


def _build_review(kind: str, label: str, start: date, end: date) -> Review:
    """Aggregate stored entries within ``[start, end]`` into a ``Review``."""
    period_entries = _load(start, end)
    missing_weeks, expected_weeks = _coverage(start, end)

    if not period_entries:
        return Review(
            period_kind=kind,  # type: ignore[arg-type]
            period_label=label,
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            totals=ReviewTotals(
                total_hours=0.0,
                meetings_hours=0.0,
                focus_hours=0.0,
                collaboration_hours=0.0,
                meeting_ratio=0.0,
                weeks_observed=0,
            ),
            delta=None,
            categories=[],
            top_labels=[],
            weekly_trend=[],
            insights=[],
            talking_points=[],
            generated_at=datetime.now(UTC),
            status="no-data",
            missing_weeks=missing_weeks,
            expected_weeks=expected_weeks,
        )

    totals = _totals(period_entries)
    categories = _categories(period_entries, totals.total_hours)
    top_labels = _top_labels(period_entries, limit=5)
    weekly = _weekly_trend(period_entries, start, end)

    # Compare against the previous period of equal length.
    prev_range = _previous_range(start, end)
    prev_entries = _load(prev_range.start, prev_range.end)
    delta = _delta(totals, prev_entries) if prev_entries else None

    insights = _insights(totals, categories, weekly, delta)
    talking_points = _talking_points(categories, top_labels, insights)

    return Review(
        period_kind=kind,  # type: ignore[arg-type]
        period_label=label,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        totals=totals,
        delta=delta,
        categories=categories,
        top_labels=top_labels,
        weekly_trend=weekly,
        insights=insights,
        talking_points=talking_points,
        generated_at=datetime.now(UTC),
        status="ok",
        missing_weeks=missing_weeks,
        expected_weeks=expected_weeks,
    )


# --- helpers ---------------------------------------------------------------


def _coverage(start: date, end: date) -> tuple[list[str], int]:
    """Return ``(missing_week_mondays, expected_week_count)`` for a period.

    A week "covers" the period if its Monday..Sunday range intersects
    ``[start, end]``. Future weeks (Monday strictly after today) are
    excluded — we don't ask the user to scan a week that hasn't happened.
    A week is "missing" when no entries are stored under that ``week_of``.
    """
    today = date.today()
    # First Monday whose week intersects the period.
    first_monday = start - timedelta(days=start.weekday())
    expected: list[str] = []
    cursor = first_monday
    while cursor <= end:
        # Skip Mondays in the future — they aren't expected to exist yet.
        if cursor <= today:
            expected.append(cursor.isoformat())
        cursor += timedelta(days=7)

    if not expected:
        return [], 0

    have = {
        e.week_of
        for e in entries_repo.list_entries_in_range(expected[0], expected[-1])
        if e.week_of
    }
    missing = [w for w in expected if w not in have]
    return missing, len(expected)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _previous_range(start: date, end: date) -> _Range:
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return _Range(prev_start, prev_end)


def _load(start: date, end: date) -> list[TimeEntry]:
    """Pull entries whose ``week_of`` Monday overlaps the period.

    A week's Monday can fall a few days before ``start``; we extend the
    lower bound by 6 days so partial weeks at the period edges are still
    included, then trim each entry's ``daily_hours`` to the actual range.
    """
    lookback = (start - timedelta(days=6)).isoformat()
    raw = entries_repo.list_entries_in_range(lookback, end.isoformat())
    trimmed: list[TimeEntry] = []
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    for entry in raw:
        days_in = {
            d: h
            for d, h in (entry.daily_hours or {}).items()
            if start_iso <= d <= end_iso
        }
        if not days_in and entry.week_of and start_iso <= entry.week_of <= end_iso:
            # No per-day breakdown but the whole week sits inside the range —
            # keep the entry with its bulk duration so it still counts.
            trimmed.append(entry)
            continue
        if not days_in:
            continue
        clipped_total = round(sum(days_in.values()), 4)
        trimmed.append(
            entry.model_copy(
                update={"duration_hours": clipped_total, "daily_hours": days_in}
            )
        )
    return trimmed


def _is_meeting(entry: TimeEntry) -> bool:
    cat = (entry.category or "").lower()
    return entry.confidence.value == "high" and cat not in {"admin", "focus"}


def _is_focus(entry: TimeEntry) -> bool:
    label = entry.label.lower()
    cat = (entry.category or "").lower()
    return label.startswith("focus") or cat == "focus"


def _is_collab(entry: TimeEntry) -> bool:
    # Collab = high-confidence meetings with 3+ identifiable participants
    # (proxy for cross-team work). We only have the entry, so use a label
    # heuristic: presence of "/" or "+" or the words sync/standup/review.
    label = entry.label.lower()
    return any(token in label for token in ("/", "+", "sync", "standup", "review"))


def _totals(period_entries: list[TimeEntry]) -> ReviewTotals:
    total = sum(e.duration_hours for e in period_entries)
    meetings = sum(e.duration_hours for e in period_entries if _is_meeting(e))
    focus = sum(e.duration_hours for e in period_entries if _is_focus(e))
    collab = sum(
        e.duration_hours for e in period_entries if _is_meeting(e) and _is_collab(e)
    )
    weeks = len({e.week_of for e in period_entries if e.week_of})
    ratio = meetings / total if total else 0.0
    return ReviewTotals(
        total_hours=round(total, 2),
        meetings_hours=round(meetings, 2),
        focus_hours=round(focus, 2),
        collaboration_hours=round(collab, 2),
        meeting_ratio=round(ratio, 4),
        weeks_observed=weeks,
    )


def _categories(
    period_entries: list[TimeEntry], total_hours: float
) -> list[CategoryBreakdown]:
    bucket: dict[str, list[TimeEntry]] = defaultdict(list)
    for e in period_entries:
        bucket[e.category or "Uncategorized"].append(e)
    out: list[CategoryBreakdown] = []
    for category, items in bucket.items():
        hours = sum(e.duration_hours for e in items)
        share = (hours / total_hours) if total_hours else 0.0
        out.append(
            CategoryBreakdown(
                category=category,
                hours=round(hours, 2),
                percent=round(share * 100, 1),
                entry_count=len(items),
            )
        )
    out.sort(key=lambda c: c.hours, reverse=True)
    return out


def _top_labels(period_entries: list[TimeEntry], *, limit: int) -> list[TopLabel]:
    bucket: dict[tuple[str, str | None], list[TimeEntry]] = defaultdict(list)
    for e in period_entries:
        bucket[(e.label, e.category)].append(e)
    rows: list[TopLabel] = []
    for (label, category), items in bucket.items():
        hours = sum(e.duration_hours for e in items)
        weeks_active = len({e.week_of for e in items if e.week_of})
        rows.append(
            TopLabel(
                label=label,
                category=category,
                hours=round(hours, 2),
                weeks_active=weeks_active,
            )
        )
    rows.sort(key=lambda r: r.hours, reverse=True)
    return rows[:limit]


def _weekly_trend(
    period_entries: list[TimeEntry], start: date, end: date
) -> list[WeeklyPoint]:
    by_week_total: dict[str, float] = defaultdict(float)
    by_week_meetings: dict[str, float] = defaultdict(float)
    by_week_focus: dict[str, float] = defaultdict(float)
    for e in period_entries:
        # Distribute by daily_hours when present so a week that spans the
        # boundary is correctly attributed.
        if e.daily_hours:
            for day_iso, hrs in e.daily_hours.items():
                week_iso = _week_monday(date.fromisoformat(day_iso)).isoformat()
                by_week_total[week_iso] += hrs
                if _is_meeting(e):
                    by_week_meetings[week_iso] += hrs
                if _is_focus(e):
                    by_week_focus[week_iso] += hrs
        elif e.week_of:
            by_week_total[e.week_of] += e.duration_hours
            if _is_meeting(e):
                by_week_meetings[e.week_of] += e.duration_hours
            if _is_focus(e):
                by_week_focus[e.week_of] += e.duration_hours

    points = [
        WeeklyPoint(
            week_of=w,
            total_hours=round(by_week_total[w], 2),
            meetings_hours=round(by_week_meetings[w], 2),
            focus_hours=round(by_week_focus[w], 2),
        )
        for w in sorted(by_week_total)
    ]
    return points


def _week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _delta(current: ReviewTotals, prev_entries: Iterable[TimeEntry]) -> ReviewDelta:
    prev_total = sum(e.duration_hours for e in prev_entries)
    prev_meetings = sum(e.duration_hours for e in prev_entries if _is_meeting(e))
    prev_focus = sum(e.duration_hours for e in prev_entries if _is_focus(e))
    prev_ratio = (prev_meetings / prev_total) if prev_total else 0.0
    return ReviewDelta(
        total_hours_delta=round(current.total_hours - prev_total, 2),
        meetings_ratio_delta=round(current.meeting_ratio - prev_ratio, 4),
        focus_hours_delta=round(current.focus_hours - prev_focus, 2),
    )


# --- insight generation (rule based) ---------------------------------------


def _insights(
    totals: ReviewTotals,
    categories: list[CategoryBreakdown],
    weekly: list[WeeklyPoint],
    delta: ReviewDelta | None,
) -> list[Insight]:
    out: list[Insight] = []

    if totals.total_hours <= 0:
        return out

    # Top category dominance.
    if categories:
        top = categories[0]
        if top.percent >= 50:
            out.append(
                Insight(
                    kind="highlight",
                    title=f"{top.category} dominates the period",
                    detail=(
                        f"{top.category} accounts for {top.percent:.0f}% of the "
                        f"{totals.total_hours:.0f}h logged ({top.hours:.0f}h)."
                    ),
                    metric=top.percent,
                )
            )

    # Meeting load.
    pct = totals.meeting_ratio * 100
    if pct >= 40:
        out.append(
            Insight(
                kind="balance",
                title="Heavy meeting load",
                detail=(
                    f"{pct:.0f}% of your time was in meetings "
                    f"({totals.meetings_hours:.0f}h)."
                ),
                metric=pct,
            )
        )

    # Period-over-period deltas.
    if delta:
        if abs(delta.total_hours_delta) >= 5:
            direction = "up" if delta.total_hours_delta > 0 else "down"
            out.append(
                Insight(
                    kind="trend",
                    title=f"Workload trending {direction}",
                    detail=(
                        f"Total hours changed by {delta.total_hours_delta:+.0f}h "
                        "vs. the previous period."
                    ),
                    metric=delta.total_hours_delta,
                )
            )
        ratio_delta_pct = delta.meetings_ratio_delta * 100
        if abs(ratio_delta_pct) >= 5:
            direction = "increased" if ratio_delta_pct > 0 else "decreased"
            out.append(
                Insight(
                    kind="trend",
                    title=f"Meeting share {direction}",
                    detail=(
                        f"Time in meetings {direction} by "
                        f"{abs(ratio_delta_pct):.0f} percentage points "
                        "vs. the previous period."
                    ),
                    metric=ratio_delta_pct,
                )
            )
        if delta.focus_hours_delta <= -5:
            out.append(
                Insight(
                    kind="balance",
                    title="Focus time eroding",
                    detail=(
                        f"Focus hours dropped by "
                        f"{abs(delta.focus_hours_delta):.0f}h vs. the previous period."
                    ),
                    metric=delta.focus_hours_delta,
                )
            )

    # Weekly variance — flag a notable spike or dip.
    if len(weekly) >= 2:
        peak = max(weekly, key=lambda p: p.total_hours)
        trough = min(weekly, key=lambda p: p.total_hours)
        if peak.total_hours - trough.total_hours >= 15:
            out.append(
                Insight(
                    kind="anomaly",
                    title="Uneven weekly workload",
                    detail=(
                        f"Peak week {peak.week_of} logged {peak.total_hours:.0f}h vs "
                        f"{trough.total_hours:.0f}h in {trough.week_of}."
                    ),
                    metric=peak.total_hours - trough.total_hours,
                )
            )

    return out


# --- talking points --------------------------------------------------------


def _talking_points(
    categories: list[CategoryBreakdown],
    top_labels: list[TopLabel],
    insights: list[Insight],
) -> list[TalkingPoint]:
    points: list[TalkingPoint] = []

    # Achievements — top labels by hours.
    for label in top_labels[:3]:
        points.append(
            TalkingPoint(
                section="achievements",
                text=(
                    f"Drove {label.label} ({label.hours:.0f}h "
                    f"across {label.weeks_active} week"
                    f"{'s' if label.weeks_active != 1 else ''})."
                ),
            )
        )

    # Focus areas — top categories.
    for cat in categories[:3]:
        points.append(
            TalkingPoint(
                section="focus",
                text=f"{cat.category}: {cat.percent:.0f}% of time ({cat.hours:.0f}h).",
            )
        )

    # Challenges — derived from balance/anomaly insights.
    for ins in insights:
        if ins.kind in ("balance", "anomaly"):
            points.append(TalkingPoint(section="challenges", text=ins.detail))

    # Asks — generic prompts the user can edit.
    if any(i.kind == "balance" and "meeting" in i.title.lower() for i in insights):
        points.append(
            TalkingPoint(
                section="asks",
                text="Discuss whether the current meeting load is sustainable.",
            )
        )
    if any(i.kind == "balance" and "focus" in i.title.lower() for i in insights):
        points.append(
            TalkingPoint(
                section="asks",
                text="Request more dedicated focus time on the calendar.",
            )
        )
    if not any(p.section == "asks" for p in points):
        points.append(
            TalkingPoint(section="asks", text="Anything you'd like more support on?")
        )

    return points
