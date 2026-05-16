"""Tests for the additive ``merge_week`` rescan path."""

from __future__ import annotations

import pytest
from wia.core.types import Confidence, Impact, TimeEntry
from wia.storage import entries as entries_repo
from wia.storage.db import get_session, init_db
from wia.storage.models import TimeEntryRow

WEEK = "2026-05-11"


def _entry(label, *, category, hours=1.0, block_ids=(), impact=Impact.MEDIUM):
    return TimeEntry(
        label=label,
        category=category,
        duration_hours=hours,
        confidence=Confidence.HIGH,
        impact=impact,
        source_block_ids=list(block_ids),
        daily_hours={},
        week_of=WEEK,
    )


@pytest.fixture(autouse=True)
def _db():
    init_db()
    # Wipe the week we use so successive tests start clean.
    entries_repo.delete_week(WEEK)
    yield
    entries_repo.delete_week(WEEK)


def _all_rows():
    with get_session() as s:
        from sqlmodel import select

        return list(s.exec(select(TimeEntryRow).where(TimeEntryRow.week_of == WEEK)))


def test_merge_inserts_new_entries_when_week_is_empty():
    entries_repo.merge_week(WEEK, [_entry("A", category="Customer", block_ids=[1])])
    rows = _all_rows()
    assert len(rows) == 1
    assert rows[0].label == "A"


def test_merge_preserves_rows_not_in_new_scan():
    # First scan: two entries.
    entries_repo.merge_week(
        WEEK,
        [
            _entry("Friedfrank – ALZ", category="Customer", block_ids=[1], hours=8.0),
            _entry("Standup", category="Internal", block_ids=[2], hours=1.0),
        ],
    )
    # Second scan returns only one of them (Copilot was flaky).
    entries_repo.merge_week(
        WEEK,
        [_entry("Standup", category="Internal", block_ids=[2], hours=1.0)],
    )
    labels = {r.label for r in _all_rows()}
    assert labels == {"Friedfrank – ALZ", "Standup"}


def test_merge_updates_in_place_by_label_category():
    entries_repo.merge_week(
        WEEK,
        [_entry("Standup", category="Internal", block_ids=[2], hours=1.0)],
    )
    entries_repo.merge_week(
        WEEK,
        [_entry("Standup", category="Internal", block_ids=[2], hours=2.5)],
    )
    rows = _all_rows()
    assert len(rows) == 1
    assert rows[0].duration_hours == 2.5


def test_merge_updates_in_place_by_block_id_when_label_changes():
    # First scan misclassified the meeting as Microsoft.
    entries_repo.merge_week(
        WEEK,
        [_entry("Microsoft – City of X", category="Microsoft", block_ids=[42], hours=3.0)],
    )
    # Second scan (with the categorization fix) puts it under Customer.
    entries_repo.merge_week(
        WEEK,
        [_entry("Customer – City of X", category="Customer", block_ids=[42], hours=3.0)],
    )
    rows = _all_rows()
    # Same row, updated in place — not two rows.
    assert len(rows) == 1
    assert rows[0].label == "Customer – City of X"
    assert rows[0].category == "Customer"


def test_merge_inserts_new_entry_when_no_match():
    entries_repo.merge_week(
        WEEK,
        [_entry("Standup", category="Internal", block_ids=[2])],
    )
    entries_repo.merge_week(
        WEEK,
        [_entry("Contoso- Azure Landing Zone ANF", category="Customer", block_ids=[99])],
    )
    labels = {r.label for r in _all_rows()}
    assert labels == {"Standup", "Contoso- Azure Landing Zone ANF"}


def test_merge_preserves_user_edited_row():
    # Seed a user-edited row directly.
    with get_session() as s:
        s.add(
            TimeEntryRow(
                label="My edited entry",
                category="Customer",
                duration_hours=5.0,
                confidence="high",
                impact="high",
                week_of=WEEK,
                source_block_ids="7",
                daily_hours="{}",
                user_edited=True,
            )
        )
        s.commit()
    # New scan tries to overwrite the same (label, category).
    entries_repo.merge_week(
        WEEK,
        [
            _entry("My edited entry", category="Customer", block_ids=[7], hours=0.5),
            _entry("Something else", category="Internal", block_ids=[8], hours=1.0),
        ],
    )
    rows = {(r.label, r.category): r for r in _all_rows()}
    edited = rows[("My edited entry", "Customer")]
    assert edited.duration_hours == 5.0  # untouched
    assert edited.user_edited is True
    assert ("Something else", "Internal") in rows


def test_merge_skips_incoming_entry_that_shares_block_with_edited_row():
    # User has manually adjusted an entry that's backed by block id 7.
    with get_session() as s:
        s.add(
            TimeEntryRow(
                label="Custom label",
                category="Customer",
                duration_hours=5.0,
                confidence="high",
                impact="high",
                week_of=WEEK,
                source_block_ids="7",
                daily_hours="{}",
                user_edited=True,
            )
        )
        s.commit()
    # New scan re-categorises the same underlying meeting (block 7) into
    # a different (label, category) \u2014 must NOT create a duplicate row.
    entries_repo.merge_week(
        WEEK,
        [_entry("Auto label", category="Microsoft", block_ids=[7], hours=2.0)],
    )
    rows = _all_rows()
    assert len(rows) == 1
    assert rows[0].user_edited is True
    assert rows[0].label == "Custom label"


def test_merge_does_not_regress_real_category_to_other():
    # First (good) scan: Outlook category was present, gave us "Customer".
    entries_repo.merge_week(
        WEEK,
        [
            _entry(
                "Suffolk – City of Suffolk sync",
                category="Suffolk",
                block_ids=[100],
                hours=1.0,
            )
        ],
    )
    # Second (flaky) scan: Copilot dropped categories_display + attendees,
    # so categorization fell through to "Other" for the same block.
    entries_repo.merge_week(
        WEEK,
        [_entry("City of Suffolk sync", category="Other", block_ids=[100], hours=1.0)],
    )
    rows = _all_rows()
    assert len(rows) == 1
    # Real label / category preserved.
    assert rows[0].category == "Suffolk"
    assert rows[0].label == "Suffolk – City of Suffolk sync"


def test_merge_does_not_regress_real_category_to_admin():
    entries_repo.merge_week(
        WEEK,
        [_entry("Customer – ContosoAzure Landing Zone", category="Customer", block_ids=[200], hours=2.0)],
    )
    # Subsequent scan with stripped metadata bucketed under Admin gap-fill.
    entries_repo.merge_week(
        WEEK,
        [_entry("Focus time", category="Admin", block_ids=[200], hours=2.0)],
    )
    rows = _all_rows()
    assert len(rows) == 1
    assert rows[0].category == "Customer"
    assert rows[0].label == "Customer – ContosoAzure Landing Zone"


def test_merge_accepts_real_category_change_between_two_real_categories():
    # Customer label -> Internal is still allowed (both non-weak).
    entries_repo.merge_week(
        WEEK,
        [_entry("Suffolk – sync", category="Suffolk", block_ids=[300], hours=1.0)],
    )
    entries_repo.merge_week(
        WEEK,
        [_entry("Customer – sync", category="Customer", block_ids=[300], hours=1.0)],
    )
    rows = _all_rows()
    assert len(rows) == 1
    assert rows[0].category == "Customer"


def test_merge_unions_source_block_ids():
    entries_repo.merge_week(
        WEEK,
        [_entry("Standup", category="Internal", block_ids=[1, 2], hours=1.0)],
    )
    entries_repo.merge_week(
        WEEK,
        [_entry("Standup", category="Internal", block_ids=[2, 3], hours=1.5)],
    )
    rows = _all_rows()
    assert len(rows) == 1
    assert set(rows[0].source_block_ids.split(",")) == {"1", "2", "3"}


def test_merge_preserves_manual_row():
    """Rows flagged ``manual=True`` (added via the manual-entry form) must
    survive a rescan even when the new scan doesn't include them."""
    with get_session() as s:
        s.add(
            TimeEntryRow(
                label="Customer call",
                category="Customer",
                duration_hours=2.0,
                confidence="high",
                impact="medium",
                week_of=WEEK,
                source_block_ids="",
                daily_hours="{}",
                user_edited=False,
                manual=True,
            )
        )
        s.commit()
    # A normal rescan returns unrelated entries — manual row should remain.
    entries_repo.merge_week(
        WEEK,
        [_entry("Standup", category="Internal", block_ids=[1], hours=1.0)],
    )
    rows = {(r.label, r.category): r for r in _all_rows()}
    assert ("Customer call", "Customer") in rows
    assert rows[("Customer call", "Customer")].manual is True
    assert rows[("Standup", "Internal")] is not None


def test_replace_week_preserves_manual_row():
    """``replace_week`` (the destructive path) must also keep manual rows."""
    with get_session() as s:
        s.add(
            TimeEntryRow(
                label="Offsite prep",
                category="Internal",
                duration_hours=3.0,
                confidence="high",
                impact="high",
                week_of=WEEK,
                source_block_ids="",
                daily_hours="{}",
                manual=True,
            )
        )
        s.commit()
    entries_repo.replace_week(
        WEEK,
        [_entry("Standup", category="Internal", block_ids=[1], hours=1.0)],
    )
    rows = {(r.label, r.category): r for r in _all_rows()}
    assert ("Offsite prep", "Internal") in rows
    assert rows[("Offsite prep", "Internal")].manual is True


def test_merge_unions_signal_sources():
    """When the same (label, category) reappears with new sources, the
    persisted ``sources`` set should be the union — provenance is sticky."""
    first = TimeEntry(
        label="Customer sync",
        category="Customer",
        duration_hours=1.0,
        confidence=Confidence.HIGH,
        impact=Impact.MEDIUM,
        source_block_ids=[1],
        daily_hours={},
        week_of=WEEK,
        sources=["calendar"],
    )
    second = TimeEntry(
        label="Customer sync",
        category="Customer",
        duration_hours=1.5,
        confidence=Confidence.HIGH,
        impact=Impact.MEDIUM,
        source_block_ids=[1],
        daily_hours={},
        week_of=WEEK,
        sources=["teams", "email"],
    )
    entries_repo.merge_week(WEEK, [first])
    entries_repo.merge_week(WEEK, [second])
    rows = _all_rows()
    assert len(rows) == 1
    persisted = sorted(s for s in rows[0].sources.split(",") if s)
    assert persisted == ["calendar", "email", "teams"]


def test_list_entries_backfills_empty_sources_with_heuristic():
    """Rows persisted before the ``sources`` column existed have an empty
    ``sources`` field. Reading them should fall back to the label-based
    heuristic so the UI always shows *some* provenance tag."""
    with get_session() as s:
        for row in (
            TimeEntryRow(
                label="Service – Re: FabrikamWin Wire",
                category="Service",
                duration_hours=0.5,
                confidence="medium",
                impact="medium",
                week_of=WEEK,
                source_block_ids="",
                daily_hours="{}",
                sources="",
            ),
            TimeEntryRow(
                label="Other – Chat with Ashton",
                category="Other",
                duration_hours=0.5,
                confidence="medium",
                impact="medium",
                week_of=WEEK,
                source_block_ids="",
                daily_hours="{}",
                sources="",
            ),
            TimeEntryRow(
                label="Customer – Contoso- Azure Landing Zone ANF",
                category="Customer",
                duration_hours=1.0,
                confidence="high",
                impact="high",
                week_of=WEEK,
                source_block_ids="",
                daily_hours="{}",
                sources="",
            ),
        ):
            s.add(row)
        s.commit()
    entries = {e.label: e.sources for e in entries_repo.list_entries(week_of=WEEK)}
    assert entries["Service – Re: FabrikamWin Wire"] == ["email"]
    assert entries["Other – Chat with Ashton"] == ["teams"]
    assert entries["Customer – Contoso- Azure Landing Zone ANF"] == ["unknown"]


def test_list_entries_does_not_backfill_manual_rows_without_sources():
    """Manual rows always carry ``[\"manual\"]``; an empty ``sources`` column\n    is a data-integrity issue but we must not invent a calendar/unknown\n    tag for a row the user explicitly marked manual."""
    with get_session() as s:
        s.add(
            TimeEntryRow(
                label="Hand-added",
                category="Customer",
                duration_hours=1.0,
                confidence="high",
                impact="medium",
                week_of=WEEK,
                source_block_ids="",
                daily_hours="{}",
                manual=True,
                sources="",
            )
        )
        s.commit()
    [entry] = entries_repo.list_entries(week_of=WEEK)
    assert entry.manual is True
    assert entry.sources == []
