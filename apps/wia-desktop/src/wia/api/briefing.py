"""Briefing endpoint — generates / retrieves a weekly briefing."""

from __future__ import annotations

import time
from datetime import date

from fastapi import APIRouter, Query

from wia.core.orchestrator import build_briefing
from wia.core.scheduler import get_scheduler
from wia.core.types import Briefing
from wia.core.week import week_bounds
from wia.storage import entries as entries_repo
from wia.storage import scan_history

router = APIRouter()


@router.get("")
async def get_briefing(
    week_of: date | None = Query(default=None, description="Any date within the target week"),
    refresh: bool = Query(default=False, description="Re-query Work IQ and rebuild"),
) -> Briefing:
    started = time.perf_counter()
    briefing = await build_briefing(week_of=week_of, refresh=refresh)
    if refresh:
        get_scheduler().record_scan(
            briefing.status,
            week_of=briefing.week_start,
            trigger="manual",
            entry_count=len(briefing.entries),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    return briefing


@router.post("/regenerate")
async def regenerate(week_of: date | None = None) -> Briefing:
    started = time.perf_counter()
    briefing = await build_briefing(week_of=week_of, refresh=True)
    get_scheduler().record_scan(
        briefing.status,
        week_of=briefing.week_start,
        trigger="manual",
        entry_count=len(briefing.entries),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return briefing


@router.delete("")
async def delete_week(
    week_of: date = Query(..., description="Any date within the target week"),
) -> dict[str, int | str]:
    """Wipe all scanned + edited entries (and scan history) for a week.

    Used by the UI's "remove week" action so the user can fully reset a
    week's data and trigger a fresh scan from scratch.
    """
    monday, _ = week_bounds(week_of)
    week_iso = monday.isoformat()
    removed_entries = entries_repo.delete_week(week_iso)
    removed_scans = scan_history.delete_for_week(week_iso)
    return {
        "week_of": week_iso,
        "deleted_entries": removed_entries,
        "deleted_scans": removed_scans,
    }
