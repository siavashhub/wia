from datetime import UTC, datetime, timedelta

from wia.core.grouping import clamp_long_blocks, dedup_across_sources, fill_gaps, merge_blocks
from wia.core.types import ActivityBlock, Confidence, Source


def _b(h_start: int, h_end: int, title="Mtg", source=Source.CALENDAR):
    return ActivityBlock(
        start=datetime(2026, 4, 20, h_start, 0, tzinfo=UTC),
        end=datetime(2026, 4, 20, h_end, 0, tzinfo=UTC),
        title=title,
        source=source,
        confidence=Confidence.HIGH,
    )


def test_merge_back_to_back_same_title():
    a = _b(9, 10, "Daily standup")
    b = _b(10, 10, "Daily standup")  # 0-min gap
    b.end = datetime(2026, 4, 20, 11, 0, tzinfo=UTC)
    out = merge_blocks([a, b])
    assert len(out) == 1
    assert out[0].duration_hours == 2.0


def test_merge_keeps_distinct_titles():
    out = merge_blocks([_b(9, 10, "A"), _b(10, 11, "B")])
    assert len(out) == 2


def test_fill_gaps_inserts_admin_and_focus():
    blocks = [_b(10, 11, "Mtg")]
    days = [datetime(2026, 4, 20, 0, 0, tzinfo=UTC)]
    out = fill_gaps(blocks, days)
    titles = [b.title for b in out]
    assert "Admin / Follow-up" in titles
    assert "Focus time" in titles


# --- cross-source dedup ---


def test_dedup_keeps_calendar_drops_teams_with_same_title():
    cal = _b(10, 11, "Friedfrank — ALZ sync", source=Source.CALENDAR)
    teams = _b(10, 11, "friedfrank alz sync", source=Source.TEAMS)
    out = dedup_across_sources([cal, teams])
    assert len(out) == 1
    assert out[0].source is Source.CALENDAR


def test_dedup_keeps_calendar_drops_email_with_re_prefix():
    cal = _b(10, 11, "ALZ Assessment", source=Source.CALENDAR)
    email = _b(10, 11, "Re: ALZ Assessment", source=Source.EMAIL)
    out = dedup_across_sources([cal, email])
    assert len(out) == 1
    assert out[0].source is Source.CALENDAR


def test_dedup_keeps_distinct_titles():
    a = _b(10, 11, "Standup", source=Source.CALENDAR)
    b = _b(14, 15, "Design review", source=Source.CALENDAR)
    out = dedup_across_sources([a, b])
    assert len(out) == 2


def test_dedup_drops_lower_priority_with_temporal_overlap():
    cal = _b(10, 12, "Workshop", source=Source.CALENDAR)
    # Email "thread" with completely different title but overlapping time.
    email = ActivityBlock(
        start=datetime(2026, 4, 20, 10, 30, tzinfo=UTC),
        end=datetime(2026, 4, 20, 11, 30, tzinfo=UTC),
        title="Re: random subject line",
        source=Source.EMAIL,
        confidence=Confidence.MEDIUM,
    )
    out = dedup_across_sources([cal, email])
    assert len(out) == 1
    assert out[0].source is Source.CALENDAR


# --- clamping ---


def test_clamp_passes_normal_block_through():
    b = _b(10, 11)
    out = clamp_long_blocks([b])
    assert len(out) == 1
    assert out[0].duration_hours == 1.0


def test_clamp_clips_teams_thread_spanning_week():
    thread = ActivityBlock(
        start=datetime(2026, 4, 20, 9, 0, tzinfo=UTC),
        end=datetime(2026, 4, 24, 17, 0, tzinfo=UTC),  # ~104h
        title="Group chat OUCH",
        source=Source.TEAMS,
        confidence=Confidence.MEDIUM,
    )
    out = clamp_long_blocks([thread], max_hours_per_day=8.0)
    assert len(out) == 1
    assert out[0].duration_hours == 8.0


def test_clamp_splits_all_day_multi_day_calendar_event():
    # Mon..Wed 24h all-day style event → emit one capped block per weekday.
    all_day = ActivityBlock(
        start=datetime(2026, 4, 20, 0, 0, tzinfo=UTC),
        end=datetime(2026, 4, 23, 0, 0, tzinfo=UTC),
        title="Conference",
        source=Source.CALENDAR,
        confidence=Confidence.HIGH,
    )
    out = clamp_long_blocks([all_day], max_hours_per_day=8.0)
    assert len(out) == 3
    assert all(b.duration_hours == 8.0 for b in out)


def test_clamp_skips_weekends_for_multiday_calendar_event():
    # Fri 12:00 UTC..Mon 12:00 UTC spans weekend → only Fri + Mon emitted.
    # Use midday to keep the local-date stable across test-runner TZs.
    fri_noon = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    all_day = ActivityBlock(
        start=fri_noon,
        end=fri_noon + timedelta(days=3),
        title="Long event",
        source=Source.CALENDAR,
        confidence=Confidence.HIGH,
    )
    out = clamp_long_blocks([all_day], max_hours_per_day=8.0)
    weekdays = {b.start.astimezone().weekday() for b in out}
    assert weekdays.issubset({0, 1, 2, 3, 4})  # no weekend days
    assert len(out) <= 3  # at most Fri + Mon (+ possible same-day-overlap)
    assert len(out) >= 2
