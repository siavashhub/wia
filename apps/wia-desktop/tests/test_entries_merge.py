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
        [_entry("CTC - AVS ANF", category="Customer", block_ids=[99])],
    )
    labels = {r.label for r in _all_rows()}
    assert labels == {"Standup", "CTC - AVS ANF"}


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
        [_entry("Customer – CTC AVS", category="Customer", block_ids=[200], hours=2.0)],
    )
    # Subsequent scan with stripped metadata bucketed under Admin gap-fill.
    entries_repo.merge_week(
        WEEK,
        [_entry("Focus time", category="Admin", block_ids=[200], hours=2.0)],
    )
    rows = _all_rows()
    assert len(rows) == 1
    assert rows[0].category == "Customer"
    assert rows[0].label == "Customer – CTC AVS"


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
