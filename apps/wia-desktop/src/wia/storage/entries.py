"""Time entry repository — converts between domain and DB rows."""

from __future__ import annotations

import json

from sqlmodel import select

from wia.core.types import Confidence, Impact, TimeEntry, TimeEntryUpdate
from wia.storage.db import get_session
from wia.storage.models import TimeEntryRow


def _row_to_entry(row: TimeEntryRow) -> TimeEntry:
    try:
        daily = json.loads(row.daily_hours) if row.daily_hours else {}
        if not isinstance(daily, dict):
            daily = {}
    except json.JSONDecodeError:
        daily = {}
    try:
        impact = Impact(row.impact) if row.impact else Impact.MEDIUM
    except ValueError:
        impact = Impact.MEDIUM
    return TimeEntry(
        id=row.id,
        label=row.label,
        category=row.category,
        duration_hours=row.duration_hours,
        confidence=Confidence(row.confidence),
        impact=impact,
        week_of=row.week_of,
        source_block_ids=[int(x) for x in row.source_block_ids.split(",") if x],
        daily_hours=daily,
    )


def _entry_to_row(entry: TimeEntry, *, user_edited: bool = False) -> TimeEntryRow:
    return TimeEntryRow(
        id=entry.id,
        label=entry.label,
        category=entry.category,
        duration_hours=entry.duration_hours,
        confidence=entry.confidence.value,
        week_of=entry.week_of or "",
        source_block_ids=",".join(str(i) for i in entry.source_block_ids),
        user_edited=user_edited,
        daily_hours=json.dumps(entry.daily_hours or {}),
        impact=entry.impact.value,
    )


def list_entries(*, week_of: str | None = None) -> list[TimeEntry]:
    with get_session() as session:
        stmt = select(TimeEntryRow)
        if week_of:
            stmt = stmt.where(TimeEntryRow.week_of == week_of)
        rows = session.exec(stmt.order_by(TimeEntryRow.duration_hours.desc())).all()
        return [_row_to_entry(r) for r in rows]


def list_entries_in_range(start_iso: str, end_iso: str) -> list[TimeEntry]:
    """Return every entry whose ``week_of`` falls in ``[start_iso, end_iso]``.

    Both bounds are ISO ``YYYY-MM-DD`` strings (inclusive). ``week_of`` is the
    Monday of the entry's week, so passing ``start_iso`` aligned to a Monday
    is the caller's responsibility.
    """
    with get_session() as session:
        stmt = (
            select(TimeEntryRow)
            .where(TimeEntryRow.week_of != "")
            .where(TimeEntryRow.week_of >= start_iso)
            .where(TimeEntryRow.week_of <= end_iso)
            .order_by(TimeEntryRow.week_of, TimeEntryRow.duration_hours.desc())
        )
        rows = session.exec(stmt).all()
        return [_row_to_entry(r) for r in rows]


def create_entry(entry: TimeEntry) -> TimeEntry:
    with get_session() as session:
        row = _entry_to_row(entry, user_edited=True)
        row.id = None
        session.add(row)
        session.commit()
        session.refresh(row)
        return _row_to_entry(row)


def update_entry(entry_id: int, update: TimeEntryUpdate) -> TimeEntry | None:
    with get_session() as session:
        row = session.get(TimeEntryRow, entry_id)
        if row is None:
            return None
        data = update.model_dump(exclude_unset=True)
        for key, val in data.items():
            setattr(row, key, val)
        row.user_edited = True
        session.add(row)
        session.commit()
        session.refresh(row)
        return _row_to_entry(row)


def delete_entry(entry_id: int) -> bool:
    with get_session() as session:
        row = session.get(TimeEntryRow, entry_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def replace_week(week_of: str, entries: list[TimeEntry]) -> None:
    """Delete non-edited entries for a week and insert fresh rows.

    User-edited rows are preserved across rescans. To avoid showing two
    rows for the same activity (one edited, one freshly aggregated) we
    skip inserting any new entry whose ``(label, category)`` collides
    with a kept user-edited row \u2014 the user's edit wins.
    """
    with get_session() as session:
        existing = session.exec(select(TimeEntryRow).where(TimeEntryRow.week_of == week_of)).all()
        kept_keys: set[tuple[str, str | None]] = set()
        for row in existing:
            if row.user_edited:
                kept_keys.add((row.label, row.category))
            else:
                session.delete(row)
        for entry in entries:
            if (entry.label, entry.category) in kept_keys:
                continue
            entry.week_of = week_of
            new_row = _entry_to_row(entry)
            new_row.id = None
            session.add(new_row)
        session.commit()


def delete_week(week_of: str) -> int:
    """Delete *every* entry for ``week_of`` — including user-edited rows.

    Returns the number of rows removed. Used by the "remove week" UI to
    fully wipe a week's scanned + edited data so the next scan starts from
    a clean slate.
    """
    with get_session() as session:
        rows = session.exec(select(TimeEntryRow).where(TimeEntryRow.week_of == week_of)).all()
        count = len(rows)
        for row in rows:
            session.delete(row)
        session.commit()
        return count
