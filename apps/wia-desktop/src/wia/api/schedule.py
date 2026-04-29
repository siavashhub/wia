"""Schedule + last-scan endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from wia.core.scheduler import ALLOWED_INTERVALS, get_scheduler
from wia.storage import scan_history

router = APIRouter()


class ScheduleStatus(BaseModel):
    interval_minutes: int
    allowed_intervals: list[int]
    last_scan_at: datetime | None
    last_scan_status: str | None
    last_scan_week_of: str | None
    last_scan_trigger: str | None


class ScheduleUpdate(BaseModel):
    interval_minutes: int


class ScanHistoryItem(BaseModel):
    id: int
    ran_at: datetime
    week_of: str
    trigger: str
    status: str
    entry_count: int
    duration_ms: int


@router.get("")
async def get_schedule() -> ScheduleStatus:
    s = get_scheduler()
    return ScheduleStatus(
        interval_minutes=s.interval_minutes,
        allowed_intervals=ALLOWED_INTERVALS,
        last_scan_at=s.last_scan_at,
        last_scan_status=s.last_scan_status,
        last_scan_week_of=s.last_scan_week_of,
        last_scan_trigger=s.last_scan_trigger,
    )


@router.put("")
async def update_schedule(update: ScheduleUpdate) -> ScheduleStatus:
    s = get_scheduler()
    try:
        s.set_interval(update.interval_minutes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await get_schedule()


@router.post("/run-now")
async def run_now() -> ScheduleStatus:
    s = get_scheduler()
    await s.run_once()
    return await get_schedule()


@router.get("/history")
async def get_history(
    limit: int = Query(default=50, ge=1, le=500),
) -> list[ScanHistoryItem]:
    """Return the most recent scan attempts (newest first)."""
    rows = scan_history.list_recent(limit=limit)
    return [
        ScanHistoryItem(
            id=r.id or 0,
            ran_at=r.ran_at,
            week_of=r.week_of,
            trigger=r.trigger,
            status=r.status,
            entry_count=r.entry_count,
            duration_ms=r.duration_ms,
        )
        for r in rows
    ]
