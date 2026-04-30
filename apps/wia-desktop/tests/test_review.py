"""Tests for the WIA Review aggregator and insight generator."""

from __future__ import annotations

import pytest
from sqlmodel import select
from wia.core import review as review_core
from wia.core.types import Confidence, TimeEntry
from wia.storage import entries as entries_repo
from wia.storage.db import get_session, init_db
from wia.storage.models import TimeEntryRow


@pytest.fixture(autouse=True)
def _reset_db() -> None:
    """Each test starts with an empty time_entry table."""
    init_db()
    with get_session() as session:
        for row in session.exec(select(TimeEntryRow)).all():
            session.delete(row)
        session.commit()


def _make(
    *,
    label: str,
    category: str,
    week_of: str,
    daily: dict[str, float],
    confidence: Confidence = Confidence.HIGH,
) -> TimeEntry:
    return TimeEntry(
        label=label,
        category=category,
        duration_hours=round(sum(daily.values()), 4),
        confidence=confidence,
        week_of=week_of,
        daily_hours=daily,
    )


def _seed_march_data() -> None:
    # Two weeks in March 2026 fully inside the month, mixed signals.
    week_a = "2026-03-02"  # Mon Mar 2
    week_b = "2026-03-09"  # Mon Mar 9

    entries_repo.create_entry(
        _make(
            label="Client A — discovery",
            category="Client A",
            week_of=week_a,
            daily={"2026-03-02": 4.0, "2026-03-03": 4.0, "2026-03-04": 2.0},
        )
    )
    entries_repo.create_entry(
        _make(
            label="Focus time",
            category="Admin",
            week_of=week_a,
            daily={"2026-03-04": 4.0, "2026-03-05": 6.0, "2026-03-06": 2.0},
            confidence=Confidence.LOW,
        )
    )
    entries_repo.create_entry(
        _make(
            label="Sprint review / sync",
            category="Client A",
            week_of=week_a,
            daily={"2026-03-06": 1.0},
        )
    )

    entries_repo.create_entry(
        _make(
            label="Client A — delivery",
            category="Client A",
            week_of=week_b,
            daily={"2026-03-09": 6.0, "2026-03-10": 6.0, "2026-03-11": 6.0},
        )
    )
    entries_repo.create_entry(
        _make(
            label="Project X kickoff",
            category="Project X",
            week_of=week_b,
            daily={"2026-03-12": 4.0, "2026-03-13": 4.0},
        )
    )


def test_parse_period_accepts_year_and_month() -> None:
    assert review_core.parse_period("2026") == ("year", 2026, None)
    assert review_core.parse_period("2026-03") == ("month", 2026, 3)


@pytest.mark.parametrize("bad", ["", "26-03", "2026-13", "2026/03", "abc"])
def test_parse_period_rejects_bad_inputs(bad: str) -> None:
    with pytest.raises(ValueError):
        review_core.parse_period(bad)


def test_monthly_review_aggregates_categories_and_top_labels() -> None:
    _seed_march_data()
    rv = review_core.build_monthly_review(2026, 3)

    assert rv.status == "ok"
    assert rv.period_kind == "month"
    assert rv.period_start == "2026-03-01"
    assert rv.period_end == "2026-03-31"
    assert rv.totals.total_hours == pytest.approx(49.0)
    assert rv.totals.weeks_observed == 2

    # Categories sorted by hours desc, with correct percent share.
    assert [c.category for c in rv.categories[:3]] == ["Client A", "Admin", "Project X"]
    # 29h Client A / 49h total ≈ 59.2%
    assert rv.categories[0].percent == pytest.approx(59.2, abs=0.2)

    # Top labels include the highest-hour activities.
    top_labels = {t.label for t in rv.top_labels}
    assert "Client A — delivery" in top_labels
    assert "Focus time" in top_labels


def test_monthly_review_emits_dominance_insight() -> None:
    _seed_march_data()
    rv = review_core.build_monthly_review(2026, 3)
    titles = [i.title for i in rv.insights]
    # Client A is ~67% of the total — should trip the dominance rule.
    assert any("Client A" in t for t in titles)


def test_monthly_review_no_data_returns_empty_review() -> None:
    rv = review_core.build_monthly_review(2025, 1)
    assert rv.status == "no-data"
    assert rv.totals.total_hours == 0.0
    assert rv.categories == []
    assert rv.talking_points == []


def test_yearly_review_includes_both_months() -> None:
    _seed_march_data()
    # Add one week in February 2026.
    entries_repo.create_entry(
        _make(
            label="Internal — planning",
            category="Internal",
            week_of="2026-02-23",  # Mon Feb 23
            daily={"2026-02-23": 4.0, "2026-02-24": 4.0, "2026-02-25": 2.0},
        )
    )
    rv = review_core.build_yearly_review(2026)
    assert rv.status == "ok"
    assert rv.period_kind == "year"
    assert rv.period_start == "2026-01-01"
    assert rv.period_end == "2026-12-31"
    assert rv.totals.total_hours == pytest.approx(59.0)
    cats = {c.category for c in rv.categories}
    assert {"Client A", "Internal", "Project X", "Admin"} <= cats


def test_talking_points_cover_main_sections() -> None:
    _seed_march_data()
    rv = review_core.build_monthly_review(2026, 3)
    sections = {p.section for p in rv.talking_points}
    assert {"achievements", "focus"} <= sections
    # An "asks" prompt is always included so the user has somewhere to start.
    assert any(p.section == "asks" for p in rv.talking_points)
