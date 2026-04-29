"""Rule-based categorization of activity blocks into time entries.

A user-editable keyword map (stored in ``user_pref``) drives project / client
detection. Internal vs client distinction uses participant email domains.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, tzinfo

from wia.core.types import ActivityBlock, Confidence, Source, TimeEntry

DEFAULT_KEYWORD_MAP: dict[str, str] = {
    # keyword (lowercase) -> category label
    "sprint": "Internal",
    "standup": "Internal",
    "1:1": "Internal",
    "all hands": "Internal",
    "design review": "Design",
    "interview": "Recruiting",
}


def _classify_title(title: str, keyword_map: dict[str, str]) -> str | None:
    t = title.lower()
    for kw, cat in keyword_map.items():
        if kw in t:
            return cat
    return None


def _client_from_participants(participants: Iterable[str], internal_domains: set[str]) -> str | None:
    external_domains: dict[str, int] = defaultdict(int)
    for email in participants:
        m = re.search(r"@([^>\s]+)", email)
        if not m:
            continue
        domain = m.group(1).lower()
        if domain in internal_domains:
            continue
        external_domains[domain] += 1
    if not external_domains:
        return None
    top = max(external_domains.items(), key=lambda kv: kv[1])[0]
    # Strip TLD for label, e.g. "client-a.com" -> "Client-A"
    label = top.split(".")[0].replace("-", " ").title()
    return label


def categorize(
    block: ActivityBlock,
    *,
    keyword_map: dict[str, str] | None = None,
    internal_domains: set[str] | None = None,
) -> tuple[str, str | None]:
    """Return (label, category) for a block."""
    keyword_map = keyword_map or DEFAULT_KEYWORD_MAP
    internal_domains = internal_domains or set()

    if block.source is Source.INFERRED:
        title = block.title or "Inferred"
        return title, "Admin"

    title = block.title or "Untitled"
    # Client (external participant) wins; keyword map is a fallback.
    client = _client_from_participants(block.participants, internal_domains)
    category = client if client is not None else _classify_title(title, keyword_map) or "Internal"

    label = f"{category} – {title}" if category and category not in title else title
    return label, category


def aggregate_entries(
    blocks: list[ActivityBlock],
    *,
    keyword_map: dict[str, str] | None = None,
    internal_domains: set[str] | None = None,
    tz: tzinfo | None = None,
) -> list[TimeEntry]:
    """Aggregate blocks into TimeEntry rows by (label, category).

    ``tz`` controls which calendar day a block is attributed to in
    ``daily_hours``. Defaults to the system local timezone.
    """
    if tz is None:
        tz = datetime.now().astimezone().tzinfo
    bucket: dict[tuple[str, str | None], list[ActivityBlock]] = defaultdict(list)
    for b in blocks:
        key = categorize(b, keyword_map=keyword_map, internal_domains=internal_domains)
        bucket[key].append(b)

    entries: list[TimeEntry] = []
    for (label, category), group in bucket.items():
        hours = sum(b.duration_hours for b in group)
        # Confidence = lowest of constituent blocks
        order = {Confidence.HIGH: 2, Confidence.MEDIUM: 1, Confidence.LOW: 0}
        conf = min((b.confidence for b in group), key=lambda c: order[c])
        daily: dict[str, float] = defaultdict(float)
        for b in group:
            day_iso = b.start.astimezone(tz).date().isoformat()
            daily[day_iso] += b.duration_hours
        entries.append(
            TimeEntry(
                label=label,
                category=category,
                duration_hours=round(hours, 2),
                confidence=conf,
                source_block_ids=[b.id for b in group if b.id is not None],
                daily_hours={k: round(v, 2) for k, v in daily.items()},
            )
        )

    entries.sort(key=lambda e: e.duration_hours, reverse=True)
    return entries
