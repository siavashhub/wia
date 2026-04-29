"""Group activity blocks into a coherent timeline.

Rules:
- Sort blocks by start time.
- Merge overlapping or back-to-back blocks (gap < ``MERGE_GAP_MINUTES``)
  if they share the same source category and label.
- Fill gaps between calendar blocks during the working day with inferred
  ``ADMIN`` blocks at low confidence.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from wia.core.types import ActivityBlock, Confidence, Source

MERGE_GAP_MINUTES = 5
WORK_DAY_START = time(9, 0)
WORK_DAY_END = time(17, 0)
MIN_GAP_FILL_MINUTES = 15


def _can_merge(a: ActivityBlock, b: ActivityBlock) -> bool:
    if a.source != b.source:
        return False
    if (a.title or "").lower() != (b.title or "").lower():
        return False
    return (b.start - a.end) <= timedelta(minutes=MERGE_GAP_MINUTES)


def merge_blocks(blocks: list[ActivityBlock]) -> list[ActivityBlock]:
    """Merge adjacent same-source same-title blocks."""
    if not blocks:
        return []
    sorted_blocks = sorted(blocks, key=lambda b: b.start)
    merged: list[ActivityBlock] = [sorted_blocks[0].model_copy(deep=True)]
    for block in sorted_blocks[1:]:
        last = merged[-1]
        if _can_merge(last, block):
            last.end = max(last.end, block.end)
            for p in block.participants:
                if p not in last.participants:
                    last.participants.append(p)
        else:
            merged.append(block.model_copy(deep=True))
    return merged


def fill_gaps(blocks: list[ActivityBlock], days: list[datetime]) -> list[ActivityBlock]:
    """Insert inferred ADMIN blocks for gaps within the working day.

    All blocks and the gap-fill window are evaluated in the timezone of
    ``days[0]`` so meetings returned with their local offset (e.g.
    ``-04:00``) line up with the user's 9-to-5 work day.
    """
    out = list(blocks)
    tz = days[0].tzinfo if days else None

    by_day: dict[str, list[ActivityBlock]] = {}
    for b in blocks:
        local_start = b.start.astimezone(tz) if tz else b.start
        by_day.setdefault(local_start.date().isoformat(), []).append(b)

    for day in days:
        day_key = day.date().isoformat()
        day_blocks = sorted(
            by_day.get(day_key, []),
            key=lambda b: b.start.astimezone(tz) if tz else b.start,
        )
        cursor = datetime.combine(day.date(), WORK_DAY_START, tzinfo=day.tzinfo)
        end_of_day = datetime.combine(day.date(), WORK_DAY_END, tzinfo=day.tzinfo)

        for block in day_blocks:
            block_start = block.start.astimezone(tz) if tz else block.start
            block_end = block.end.astimezone(tz) if tz else block.end
            if block_start > cursor:
                gap = block_start - cursor
                if gap >= timedelta(minutes=MIN_GAP_FILL_MINUTES):
                    out.append(
                        ActivityBlock(
                            start=cursor,
                            end=block_start,
                            title="Admin / Follow-up",
                            source=Source.INFERRED,
                            confidence=Confidence.LOW,
                        )
                    )
            cursor = max(cursor, block_end)

        if cursor < end_of_day and (end_of_day - cursor) >= timedelta(minutes=MIN_GAP_FILL_MINUTES):
            out.append(
                ActivityBlock(
                    start=cursor,
                    end=end_of_day,
                    title="Focus time",
                    source=Source.INFERRED,
                    confidence=Confidence.LOW,
                )
            )

    return sorted(out, key=lambda b: b.start)
