"""Briefing endpoint — generates / retrieves a weekly briefing."""

from __future__ import annotations

import time
from datetime import date

from fastapi import APIRouter, Query

from wia.core.orchestrator import build_briefing
from wia.core.scheduler import get_scheduler
from wia.core.types import Briefing

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
