"""Time-entry CRUD endpoints."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from wia.core.types import Confidence, Impact, TimeEntry, TimeEntryUpdate
from wia.core.week import week_bounds
from wia.storage import entries as repo

router = APIRouter()


class ManualEntryCreate(BaseModel):
    """Payload for adding a manual entry from the Briefing UI.

    Either ``daily_hours`` or ``duration_hours`` must be provided. When
    both are present, ``daily_hours`` wins and ``duration_hours`` is
    recomputed from its sum.
    """

    label: str = Field(min_length=1)
    category: str | None = None
    week_of: str | None = None  # ISO Monday; derived from daily_hours if omitted
    duration_hours: float | None = None
    daily_hours: dict[str, float] = Field(default_factory=dict)
    impact: Impact = Impact.MEDIUM
    notes: str = ""


@router.get("")
async def list_entries(week_of: str | None = None) -> list[TimeEntry]:
    return repo.list_entries(week_of=week_of)


@router.patch("/{entry_id}")
async def update_entry(entry_id: int, update: TimeEntryUpdate) -> TimeEntry:
    updated = repo.update_entry(entry_id, update)
    if updated is None:
        raise HTTPException(status_code=404, detail="entry not found")
    return updated


@router.post("")
async def create_entry(payload: ManualEntryCreate) -> TimeEntry:
    # Normalise daily_hours and derive duration when needed.
    daily = {d: float(h) for d, h in (payload.daily_hours or {}).items() if float(h) > 0}
    if daily:
        duration = round(sum(daily.values()), 4)
    elif payload.duration_hours is not None:
        duration = round(float(payload.duration_hours), 4)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either duration_hours or non-empty daily_hours.",
        )
    if duration <= 0:
        raise HTTPException(status_code=400, detail="duration_hours must be > 0.")

    # Derive week_of (Monday) from the first daily-hours date if missing.
    week_of = payload.week_of
    if not week_of and daily:
        first_day = sorted(daily.keys())[0]
        try:
            week_of = (
                date.fromisoformat(first_day)
                - timedelta(days=date.fromisoformat(first_day).weekday())
            ).isoformat()
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid day in daily_hours: {exc}"
            ) from exc
    if not week_of:
        # Fall back to the current week's Monday.
        monday, _ = week_bounds(None)
        week_of = monday.isoformat()

    entry = TimeEntry(
        label=payload.label.strip(),
        category=(payload.category or "").strip() or None,
        duration_hours=duration,
        confidence=Confidence.HIGH,
        impact=payload.impact,
        week_of=week_of,
        source_block_ids=[],
        daily_hours=daily,
        notes=payload.notes or "",
        manual=True,
        sources=["manual"],
    )
    return repo.create_entry(entry)


@router.delete("/{entry_id}")
async def delete_entry(entry_id: int) -> dict[str, bool]:
    if not repo.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="entry not found")
    return {"deleted": True}
