"""Group activity blocks into a coherent timeline.

Rules:
- Sort blocks by start time.
- Merge overlapping or back-to-back blocks (gap < ``MERGE_GAP_MINUTES``)
  if they share the same source category and label.
- Fill gaps between calendar blocks during the working day with inferred
  ``ADMIN`` blocks at low confidence.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta

from wia.core.types import ActivityBlock, Confidence, Source

MERGE_GAP_MINUTES = 5
WORK_DAY_START = time(9, 0)
WORK_DAY_END = time(17, 0)
MIN_GAP_FILL_MINUTES = 15
# Cap any single calendar day's contribution from one block. Work IQ can
# return Teams "ongoing thread" / email "long-running thread" blocks whose
# start/end span the entire week — at face value those would balloon a
# weekly briefing past 90 hours for a single conversation. We assume no
# one is engaged with a single thread for more than a full work day.
MAX_HOURS_PER_BLOCK_PER_DAY = 8.0
# Calendar > Teams > Email when two signals describe the same activity.
_SOURCE_PRIORITY: dict[Source, int] = {
    Source.CALENDAR: 3,
    Source.TEAMS: 2,
    Source.EMAIL: 1,
    Source.INFERRED: 0,
}


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


_TITLE_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize_title(title: str | None) -> str:
    """Lowercase, strip ``Re:``/``Fwd:`` and non-alphanumerics for fuzzy match."""
    if not title:
        return ""
    t = title.lower().strip()
    while True:
        stripped = re.sub(r"^(re|fwd|fw)\s*:\s*", "", t)
        if stripped == t:
            break
        t = stripped
    return _TITLE_NORMALIZE_RE.sub(" ", t).strip()


def _temporal_overlap(a: ActivityBlock, b: ActivityBlock) -> float:
    """Return overlap as a fraction of the shorter block's duration (0..1)."""
    start = max(a.start, b.start)
    end = min(a.end, b.end)
    overlap = (end - start).total_seconds()
    if overlap <= 0:
        return 0.0
    shorter = min(
        (a.end - a.start).total_seconds(),
        (b.end - b.start).total_seconds(),
    )
    if shorter <= 0:
        return 0.0
    return overlap / shorter


def dedup_across_sources(
    blocks: list[ActivityBlock], *, overlap_threshold: float = 0.5
) -> list[ActivityBlock]:
    """Drop teams/email blocks that duplicate a calendar (or higher-priority)
    block.

    Work IQ returns the same meeting through multiple lenses: a calendar
    event, a Teams chat thread for the same group, and an email thread
    on the same subject. Naïvely summing all three triple-counts the
    hours. We keep one block per ``(normalised title, day)`` cluster,
    preferring the highest-priority source (calendar > teams > email).

    Two blocks are considered the same activity when **either**:
    - their normalised titles match exactly, **or**
    - they share ≥ ``overlap_threshold`` of the shorter block's duration.
    """
    if not blocks:
        return []
    # Sort by source priority so calendar entries are inspected first
    # and become "winners" against later teams/email duplicates.
    ordered = sorted(
        blocks,
        key=lambda b: (-_SOURCE_PRIORITY.get(b.source, 0), b.start),
    )
    kept: list[ActivityBlock] = []
    dropped = 0
    for cand in ordered:
        norm = _normalize_title(cand.title)
        is_dup = False
        for k in kept:
            if _SOURCE_PRIORITY.get(k.source, 0) < _SOURCE_PRIORITY.get(cand.source, 0):
                continue
            if norm and norm == _normalize_title(k.title):
                is_dup = True
                break
            if _temporal_overlap(cand, k) >= overlap_threshold:
                # Same time window from a lower-priority signal — drop.
                is_dup = True
                break
        if is_dup:
            dropped += 1
            continue
        kept.append(cand)
    if dropped:
        import logging

        logging.getLogger(__name__).info(
            "Cross-source dedup dropped %d/%d block(s) as duplicates of a higher-priority signal",
            dropped,
            len(blocks),
        )
    return sorted(kept, key=lambda b: b.start)


def clamp_long_blocks(
    blocks: list[ActivityBlock],
    *,
    max_hours_per_day: float = MAX_HOURS_PER_BLOCK_PER_DAY,
) -> list[ActivityBlock]:
    """Split / clamp blocks that span multiple calendar days or exceed the
    per-day cap.

    Work IQ frequently returns:

    - Outlook all-day events with ``end - start == 24h`` (full midnight
      to midnight) — splitting on day boundary and capping to
      ``max_hours_per_day`` per day prevents a single all-day item from
      contributing 24h to a single bucket.
    - Teams "ongoing thread" / email long-thread blocks with start/end
      spanning the whole week. We can't know which day the user was
      actually engaged, so we attribute up to ``max_hours_per_day`` to
      the *start day* and drop the rest. Anything else would be making
      up data.

    Single-day blocks shorter than the cap pass through unchanged.
    """
    out: list[ActivityBlock] = []
    for b in blocks:
        duration_h = (b.end - b.start).total_seconds() / 3600.0
        start_local = b.start.astimezone()
        end_local = b.end.astimezone()
        same_day = start_local.date() == end_local.date()
        # Common case: single-day block within the cap → keep as-is.
        if same_day and duration_h <= max_hours_per_day:
            out.append(b)
            continue
        # Synthetic gap-fill blocks should never need clamping; skip the
        # work but guard against pathological inputs.
        if b.source is Source.INFERRED:
            if duration_h <= max_hours_per_day:
                out.append(b)
            else:
                clipped = b.model_copy(deep=True)
                clipped.end = b.start + timedelta(hours=max_hours_per_day)
                out.append(clipped)
            continue
        # Multi-day calendar block (typically an Outlook all-day series):
        # emit one capped block per calendar day in the range.
        if not same_day and b.source is Source.CALENDAR:
            day = start_local.date()
            last_day = end_local.date()
            while day <= last_day:
                # Skip weekends for all-day spans — they're almost never
                # representative of real work time.
                if day.weekday() < 5:
                    day_start = datetime.combine(day, time(9, 0), tzinfo=start_local.tzinfo)
                    day_end = day_start + timedelta(hours=max_hours_per_day)
                    piece = b.model_copy(deep=True)
                    piece.start = day_start
                    piece.end = day_end
                    out.append(piece)
                day = day + timedelta(days=1)
            continue
        # Teams/email "thread" block: clamp to the cap, attributed to the
        # start day. We deliberately don't fan it out across days because
        # we have no signal for which days were active.
        clipped = b.model_copy(deep=True)
        clipped.end = b.start + timedelta(hours=max_hours_per_day)
        out.append(clipped)
    return out


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
