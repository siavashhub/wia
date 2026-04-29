"""Briefing orchestrator — fetches signals, builds blocks/entries, persists."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, date, datetime

from wia.core.categorization import aggregate_entries
from wia.core.grouping import fill_gaps, merge_blocks
from wia.core.types import (
    ActivityBlock,
    Briefing,
    BriefingTotals,
    Source,
    TimeEntry,
    WorkAreaSummary,
)
from wia.core.week import week_bounds, week_days
from wia.mcp_clients.workiq import get_workiq_client
from wia.storage import entries as entries_repo

log = logging.getLogger(__name__)


def _totals(blocks: list[ActivityBlock]) -> BriefingTotals:
    meetings = sum(b.duration_hours for b in blocks if b.source is Source.CALENDAR)
    focus = sum(
        b.duration_hours
        for b in blocks
        if b.source is Source.INFERRED and (b.title or "").lower().startswith("focus")
    )
    collab = sum(
        b.duration_hours
        for b in blocks
        if b.source in {Source.TEAMS, Source.EMAIL}
    )
    total = sum(b.duration_hours for b in blocks)
    return BriefingTotals(
        total_hours=round(total, 2),
        meetings_hours=round(meetings, 2),
        focus_hours=round(focus, 2),
        collaboration_hours=round(collab, 2),
    )


def _top_work_areas(entries: list[TimeEntry], limit: int = 5) -> list[WorkAreaSummary]:
    by_cat: dict[str, float] = defaultdict(float)
    for e in entries:
        by_cat[e.category or "Uncategorized"] += e.duration_hours
    items = sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [WorkAreaSummary(label=k, hours=round(v, 2)) for k, v in items]


async def build_briefing(
    *,
    week_of: date | None = None,
    refresh: bool = False,
    signals: list[str] | None = None,
) -> Briefing:
    monday, sunday = week_bounds(week_of)
    week_iso = monday.isoformat()
    log.info("Building briefing for week %s..%s (refresh=%s)", monday, sunday, refresh)

    # 0. Cache short-circuit: when the caller did not ask for a refresh we
    # never contact Work IQ. If we have cached entries for this week we
    # return them; otherwise we return an empty "no-signals" briefing so
    # the UI can show the empty state and let the user opt in to a scan.
    # This prevents week navigation (Prev/Next) from silently triggering
    # an MCP scan against Work IQ for weeks that have never been scanned.
    if not refresh:
        cached = entries_repo.list_entries(week_of=week_iso)
        if cached:
            log.info("Using cached briefing for %s (%d entries)", week_iso, len(cached))
            return Briefing(
                week_start=monday.isoformat(),
                week_end=sunday.isoformat(),
                totals=_totals_from_entries(cached),
                top_work_areas=_top_work_areas(cached),
                entries=cached,
                blocks=[],
                generated_at=datetime.now(UTC),
                status="ok",
            )
        log.info("No cached briefing for %s; skipping Work IQ scan (refresh=False)", week_iso)
        return Briefing(
            week_start=monday.isoformat(),
            week_end=sunday.isoformat(),
            totals=BriefingTotals(total_hours=0, meetings_hours=0, focus_hours=0, collaboration_hours=0),
            top_work_areas=[],
            entries=[],
            blocks=[],
            generated_at=datetime.now(UTC),
            status="no-signals",
        )

    # Determine which signals to pull. Default to user prefs.
    if signals is None:
        # Imported here to avoid a circular import at module load time.
        from wia.api.prefs import get_enabled_signals
        signals = get_enabled_signals()
    log.info("Scanning enabled signals: %s", signals)

    # 1. Fetch enabled signals from Work IQ MCP, in parallel.
    client = get_workiq_client()
    coros: list = []
    kinds: list[str] = []
    if "calendar" in signals:
        coros.append(client.fetch_calendar_blocks(monday, sunday))
        kinds.append("calendar")
    if "teams" in signals:
        coros.append(client.fetch_teams_blocks(monday, sunday))
        kinds.append("teams")
    if "email" in signals:
        coros.append(client.fetch_email_blocks(monday, sunday))
        kinds.append("email")

    if not coros:
        # User disabled every signal — nothing to scan, return empty briefing.
        return Briefing(
            week_start=monday.isoformat(),
            week_end=sunday.isoformat(),
            totals=BriefingTotals(total_hours=0, meetings_hours=0, focus_hours=0, collaboration_hours=0),
            top_work_areas=[],
            entries=[],
            blocks=[],
            generated_at=datetime.now(UTC),
            status="no-signals",
        )

    raw_blocks: list[ActivityBlock] = []
    workiq_failed = False
    results = await asyncio.gather(*coros, return_exceptions=True)
    for kind, res in zip(kinds, results, strict=True):
        if isinstance(res, Exception):
            log.warning("Work IQ %s fetch failed: %s", kind, res)
            workiq_failed = True
            continue
        raw_blocks.extend(res)

    if workiq_failed and not raw_blocks:
        return Briefing(
            week_start=monday.isoformat(),
            week_end=sunday.isoformat(),
            totals=BriefingTotals(total_hours=0, meetings_hours=0, focus_hours=0, collaboration_hours=0),
            top_work_areas=[],
            entries=[],
            blocks=[],
            generated_at=datetime.now(UTC),
            status="workiq-not-enabled",
        )

    # 2. Group + (only if we have real signals) fill gaps.
    # When Work IQ returns zero events we deliberately skip gap-filling so
    # we don't synthesize 40 fake hours of "Admin" for an empty week.
    # Gap-filling only runs on weekdays — we don't want to synthesize
    # phantom "Focus time" on Saturday and Sunday.
    merged = merge_blocks(raw_blocks)
    if merged:
        days = [d for d in week_days(monday) if d.weekday() < 5]
        all_blocks = fill_gaps(merged, days)
    else:
        all_blocks = []

    # 3. Categorize → entries
    entries = aggregate_entries(all_blocks)
    for e in entries:
        e.week_of = week_iso

    # 4. Persist (replace existing for this week unless user has manual edits)
    entries_repo.replace_week(week_iso, entries)
    entries = entries_repo.list_entries(week_of=week_iso)

    return Briefing(
        week_start=monday.isoformat(),
        week_end=sunday.isoformat(),
        totals=_totals(all_blocks),
        top_work_areas=_top_work_areas(entries),
        entries=entries,
        blocks=all_blocks,
        generated_at=datetime.now(UTC),
        status="ok" if all_blocks else "no-signals",
    )


def _totals_from_entries(entries: list[TimeEntry]) -> BriefingTotals:
    """Approximate totals when we don't have live blocks (cache path).

    Calendar/meeting hours are inferred from confidence: ``HIGH`` entries
    correspond to real calendar meetings; ``LOW`` entries are gap-fill
    (admin/focus). We treat focus-time entries by label.
    """
    meetings = sum(e.duration_hours for e in entries if e.confidence.value == "high")
    focus = sum(
        e.duration_hours for e in entries if (e.label or "").lower().startswith("focus")
    )
    total = sum(e.duration_hours for e in entries)
    return BriefingTotals(
        total_hours=round(total, 2),
        meetings_hours=round(meetings, 2),
        focus_hours=round(focus, 2),
        collaboration_hours=0.0,
    )
