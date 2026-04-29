from datetime import UTC, datetime

from wia.core.grouping import fill_gaps, merge_blocks
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
