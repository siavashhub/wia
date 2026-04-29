"""Time-entry CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from wia.core.types import TimeEntry, TimeEntryUpdate
from wia.storage import entries as repo

router = APIRouter()


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
async def create_entry(entry: TimeEntry) -> TimeEntry:
    return repo.create_entry(entry)


@router.delete("/{entry_id}")
async def delete_entry(entry_id: int) -> dict[str, bool]:
    if not repo.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="entry not found")
    return {"deleted": True}
