"""Time entry repository — converts between domain and DB rows."""

from __future__ import annotations

import json

from sqlmodel import select

from wia.core.categorization import infer_sources_from_label
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
        impact = Impact(row.impact) if row.impact else Impact.LOW
    except ValueError:
        # Legacy ``medium`` rows (and any other unknown value) collapse to
        # LOW under the v0.4 binary scale.
        impact = Impact.LOW
    sources = [s for s in (row.sources or "").split(",") if s]
    if not sources and not row.manual:
        # Backfill rows that pre-date the ``sources`` column with a
        # best-guess from the label so the UI shows *some* tag. Manual
        # rows already get ``["manual"]`` at create-time; don't override.
        sources = infer_sources_from_label(row.label, row.category)
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
        notes=row.notes or "",
        manual=bool(row.manual),
        sources=sources,
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
        notes=entry.notes or "",
        manual=bool(entry.manual),
        sources=",".join(entry.sources or []),
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
        # Entries created through this path come from the UI's manual-add
        # flow — flag them so a subsequent rescan won't overwrite them.
        entry.manual = True
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
            if key == "impact" and val is not None:
                # Pydantic dump leaves enums as enum instances by default.
                setattr(row, key, val.value if hasattr(val, "value") else str(val))
            elif key == "daily_hours":
                row.daily_hours = json.dumps(val or {})
                if val:
                    row.duration_hours = round(sum(float(v) for v in val.values()), 4)
            else:
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
            if row.user_edited or row.manual:
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


def _row_block_ids(row: TimeEntryRow) -> set[int]:
    return {int(x) for x in row.source_block_ids.split(",") if x}


# Categories we treat as "no real signal" — a later scan that produces one
# of these for an event we previously labelled with a real category is
# almost always Copilot dropping the ``categories_display`` /
# ``participants`` metadata, not a genuine re-categorisation. Don't let
# such a scan regress a good earlier label.
_WEAK_CATEGORIES = frozenset({"Other", "Admin"})


def merge_week(week_of: str, entries: list[TimeEntry]) -> None:
    """Refresh a week with the latest scan, preserving only user edits.

    Matching logic for "is this incoming entry already in the DB?":

    1. **Block-id overlap** — any non-edited existing row whose
       ``source_block_ids`` shares at least one id with the incoming
       entry's ids. Catches the case where a previous categorisation bug
       has been fixed and the same underlying meeting now has a
       different ``(label, category)``.
    2. **(label, category) match** — fallback for synthetic blocks
       (Admin / Focus time) and any entries with no recorded
       ``source_block_ids``.

    Regression guard: when the matched row already has a "real" category
    (anything other than ``Other`` / ``Admin``) and the incoming entry
    has a weak one, we keep the existing label/category and only refresh
    the volatile fields (hours, impact, daily breakdown). This stops a
    flaky rescan that lost an event's ``categories_display`` metadata
    from demoting a previously-good Customer row to ``Other``.

    Orphan sweep: once the incoming entries have all been applied, any
    leftover non-edited row that the current scan did not match is
    deleted. This is the only way to get a clean week in builds where
    activity blocks aren't persisted with stable ids — without it, every
    rescan that produces a slightly different label, category or
    cleaned-up title accumulates an orphan row and the week's totals
    drift upward indefinitely.

    Safety guards:

    - User-edited rows (``user_edited=True``) and manual rows
      (``manual=True``) are partitioned out at the start and never
      touched by the sweep.
    - The sweep is skipped entirely when ``entries`` is empty so a
      failed scan that produced no signals can't wipe an existing
      week.

    Use :func:`delete_week` for an unconditional wipe (including manual
    and user-edited rows) and :func:`replace_week` for a clean rebuild
    that still keeps manual rows.
    """
    with get_session() as session:
        existing = session.exec(select(TimeEntryRow).where(TimeEntryRow.week_of == week_of)).all()
        # Partition existing rows so we can match incoming entries by block-id
        # overlap (preferred) and then by (label, category) as a fallback.
        non_edited: list[TimeEntryRow] = []
        edited_keys: set[tuple[str, str | None]] = set()
        edited_block_ids: set[int] = set()
        for row in existing:
            if row.user_edited or row.manual:
                edited_keys.add((row.label, row.category))
                edited_block_ids.update(_row_block_ids(row))
            else:
                non_edited.append(row)
        by_key: dict[tuple[str, str | None], TimeEntryRow] = {
            (r.label, r.category): r for r in non_edited
        }
        by_block_id: dict[int, TimeEntryRow] = {}
        for r in non_edited:
            for bid in _row_block_ids(r):
                by_block_id[bid] = r

        for entry in entries:
            entry.week_of = week_of
            key = (entry.label, entry.category)
            # 1. User-edited row wins outright. Don't insert a duplicate.
            if key in edited_keys:
                continue
            entry_block_ids = {i for i in entry.source_block_ids if i is not None}
            # If any incoming block id belongs to a user-edited row, skip
            # \u2014 the user has spoken for that activity.
            if entry_block_ids & edited_block_ids:
                continue

            # 2. Match by block-id overlap first (covers re-categorisations).
            target: TimeEntryRow | None = None
            for bid in entry_block_ids:
                if bid in by_block_id:
                    target = by_block_id[bid]
                    break
            # 3. Fall back to (label, category) match.
            if target is None:
                target = by_key.get(key)

            if target is not None:
                # Remember the row's pre-update key so the sweep below
                # doesn't drop it after we mutate ``target.label`` /
                # ``target.category`` in place.
                old_key = (target.label, target.category)
                # In-place update; the latest scan is truth for hours/impact.
                # Regression guard: a weak incoming category (Other/Admin)
                # over a real existing one is almost always Copilot
                # dropping metadata, not a genuine re-categorisation.
                existing_strong = (target.category or "") not in _WEAK_CATEGORIES
                incoming_weak = (entry.category or "") in _WEAK_CATEGORIES
                if not (existing_strong and incoming_weak):
                    target.label = entry.label
                    target.category = entry.category
                target.duration_hours = entry.duration_hours
                target.confidence = entry.confidence.value
                target.impact = entry.impact.value
                # Union the block-id sets so we don't lose provenance from
                # earlier scans when an incoming entry only reports a
                # subset.
                merged_ids = sorted(_row_block_ids(target) | entry_block_ids)
                target.source_block_ids = ",".join(str(i) for i in merged_ids)
                # Union signal-source tags too — provenance is sticky.
                merged_sources = sorted(
                    {s for s in (target.sources or "").split(",") if s} | set(entry.sources or [])
                )
                target.sources = ",".join(merged_sources)
                target.daily_hours = json.dumps(entry.daily_hours or {})
                session.add(target)
                # Refresh indexes so a later incoming entry doesn't also
                # match this same row, and so the sweep below doesn't
                # treat the refreshed row as an orphan.
                by_key.pop(old_key, None)
                for bid in list(by_block_id):
                    if by_block_id[bid] is target:
                        by_block_id.pop(bid, None)
            else:
                new_row = _entry_to_row(entry)
                new_row.id = None
                session.add(new_row)

        # Orphan sweep. Any non-edited row still in ``by_key`` was not
        # matched (and therefore not refreshed) by the current scan —
        # the underlying activity is no longer reported by Work IQ, or
        # the new scan produced a slightly different ``(label,
        # category)`` for it and created a fresh row above. Either way,
        # the stale row no longer represents truth and would otherwise
        # accumulate forever. Skip the sweep entirely when the scan
        # returned nothing so a failed signal can't wipe the week.
        if entries:
            for stale in by_key.values():
                session.delete(stale)
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
