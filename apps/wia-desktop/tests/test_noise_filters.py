"""Tests for the hotfix/0.3.1 noise-reduction ingest filters.

Exercises the three new ``_should_drop_*`` helpers in
:mod:`wia.core.orchestrator` directly so we don't need to spin up a
Work IQ MCP roundtrip. End-to-end coverage via ``build_briefing`` is
implicit: the helpers are the only place those filters are applied.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from wia.core.orchestrator import (
    _should_drop_by_optional_attendance,
    _should_drop_by_response,
    _should_drop_passive_teams,
    _should_drop_small_email,
)
from wia.core.types import ActivityBlock, Confidence, Source


def _cal(title: str = "Meeting", *, metadata: dict[str, str] | None = None) -> ActivityBlock:
    return ActivityBlock(
        start=datetime(2026, 4, 20, 9, 0, tzinfo=UTC),
        end=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
        title=title,
        participants=["a@example.com"],
        source=Source.CALENDAR,
        confidence=Confidence.HIGH,
        metadata=dict(metadata or {}),
    )


def _email(*, hours: float, metadata: dict[str, str] | None = None) -> ActivityBlock:
    start = datetime(2026, 4, 20, 9, 0, tzinfo=UTC)
    return ActivityBlock(
        start=start,
        end=start + timedelta(hours=hours),
        title="thread",
        participants=[],
        source=Source.EMAIL,
        confidence=Confidence.MEDIUM,
        metadata=dict(metadata or {}),
    )


# --- response-status filter ----------------------------------------------------


def test_declined_dropped_when_enabled():
    b = _cal(metadata={"response_status": "declined"})
    assert _should_drop_by_response(b, drop_declined=True, drop_no_resp=False)


def test_declined_kept_when_disabled():
    b = _cal(metadata={"response_status": "declined"})
    assert not _should_drop_by_response(b, drop_declined=False, drop_no_resp=True)


def test_not_responded_dropped_when_enabled():
    b = _cal(metadata={"response_status": "notresponded"})
    assert _should_drop_by_response(b, drop_declined=False, drop_no_resp=True)


def test_organizer_never_dropped():
    b = _cal(metadata={"response_status": "organizer"})
    assert not _should_drop_by_response(b, drop_declined=True, drop_no_resp=True)


def test_missing_response_status_kept():
    # No metadata at all — the filter has nothing to evaluate, so the
    # block survives. The orchestrator logs a WARNING separately.
    b = _cal()
    assert not _should_drop_by_response(b, drop_declined=True, drop_no_resp=True)


def test_non_calendar_block_skipped_by_response_filter():
    b = _email(hours=2.0, metadata={"response_status": "declined"})
    assert not _should_drop_by_response(b, drop_declined=True, drop_no_resp=True)


def test_response_filter_short_circuits_when_both_disabled():
    b = _cal(metadata={"response_status": "declined"})
    assert not _should_drop_by_response(b, drop_declined=False, drop_no_resp=False)


# --- optional + large filter ---------------------------------------------------


def test_optional_large_dropped_when_threshold_met():
    b = _cal(metadata={"is_optional": "true", "attendee_count": "25"})
    assert _should_drop_by_optional_attendance(b, min_attendees=20)


def test_optional_large_kept_when_below_threshold():
    b = _cal(metadata={"is_optional": "true", "attendee_count": "10"})
    assert not _should_drop_by_optional_attendance(b, min_attendees=20)


def test_not_optional_kept_regardless_of_attendee_count():
    b = _cal(metadata={"is_optional": "false", "attendee_count": "200"})
    assert not _should_drop_by_optional_attendance(b, min_attendees=20)


def test_optional_organizer_never_dropped():
    # Pathological but possible (Outlook lets you mark yourself Optional on
    # an event you organised).
    b = _cal(
        metadata={
            "is_optional": "true",
            "attendee_count": "500",
            "response_status": "organizer",
        }
    )
    assert not _should_drop_by_optional_attendance(b, min_attendees=20)


def test_missing_attendee_count_kept():
    b = _cal(metadata={"is_optional": "true"})
    assert not _should_drop_by_optional_attendance(b, min_attendees=20)


def test_garbage_attendee_count_kept():
    b = _cal(metadata={"is_optional": "true", "attendee_count": "not-a-number"})
    assert not _should_drop_by_optional_attendance(b, min_attendees=20)


# --- email-thread-size filter --------------------------------------------------


def test_short_email_dropped():
    assert _should_drop_small_email(_email(hours=0.05), min_hours=0.1)


def test_long_email_kept():
    assert not _should_drop_small_email(_email(hours=1.0), min_hours=0.1)


def test_email_filter_disabled_when_threshold_zero():
    assert not _should_drop_small_email(_email(hours=0.001), min_hours=0)


def test_email_filter_does_not_touch_calendar_blocks():
    short_cal = _cal()
    short_cal.end = short_cal.start  # zero-length cal block
    assert not _should_drop_small_email(short_cal, min_hours=1.0)


# --- passive Teams thread filter ----------------------------------------------


def _teams(*, metadata: dict[str, str] | None = None) -> ActivityBlock:
    return ActivityBlock(
        start=datetime(2026, 4, 20, 9, 0, tzinfo=UTC),
        end=datetime(2026, 4, 20, 9, 30, tzinfo=UTC),
        title="thread",
        participants=[],
        source=Source.TEAMS,
        confidence=Confidence.MEDIUM,
        metadata=dict(metadata or {}),
    )


def test_passive_teams_dropped_when_iparticipated_false():
    assert _should_drop_passive_teams(_teams(metadata={"i_participated": "false"}))


def test_active_teams_kept_when_iparticipated_true():
    assert not _should_drop_passive_teams(_teams(metadata={"i_participated": "true"}))


def test_teams_kept_when_iparticipated_missing():
    # Missing metadata is "unknown" — never causes a drop, so noisy Work
    # IQ that stops returning the field can't silently lose data.
    assert not _should_drop_passive_teams(_teams())


def test_passive_filter_does_not_touch_calendar_or_email():
    cal = _cal(metadata={"i_participated": "false"})
    em = _email(hours=2.0, metadata={"i_participated": "false"})
    assert not _should_drop_passive_teams(cal)
    assert not _should_drop_passive_teams(em)
