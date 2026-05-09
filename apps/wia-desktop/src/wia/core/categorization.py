"""Rule-based categorization of activity blocks into time entries.

A user-editable keyword map (stored in ``user_pref``) drives project / client
detection. Internal vs client distinction uses participant email domains.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, tzinfo

from wia.core.types import ActivityBlock, Confidence, Impact, Source, TimeEntry

DEFAULT_KEYWORD_MAP: dict[str, str] = {
    # keyword (lowercase) -> category label
    "sprint": "Internal",
    "standup": "Internal",
    "1:1": "Internal",
    "all hands": "Internal",
    "design review": "Design",
    "interview": "Recruiting",
}

# Categories that default to "low impact" — i.e. de-emphasized in WIA Review
# unless the user explicitly tags an entry as high impact. Internal sprints,
# standups, all-hands etc. live here; the user's own organization label
# (e.g. "Microsoft") is appended at runtime.
DEFAULT_LOW_IMPACT_CATEGORIES: frozenset[str] = frozenset({"internal", "admin"})


def default_impact_for_category(
    category: str | None,
    *,
    organization_label: str | None = None,
    extra_low_impact: Iterable[str] = (),
) -> Impact:
    """Return the default :class:`Impact` for an entry with ``category``.

    - ``Internal`` and ``Admin`` (case-insensitive) → :attr:`Impact.LOW`.
    - The user's organization label (e.g. ``"Microsoft"``) → :attr:`Impact.LOW`.
    - Anything else → :attr:`Impact.MEDIUM`.
    """
    if not category:
        return Impact.MEDIUM
    cat_lower = category.strip().lower()
    if not cat_lower:
        return Impact.MEDIUM
    low_set = set(DEFAULT_LOW_IMPACT_CATEGORIES)
    if organization_label:
        org_lower = organization_label.strip().lower()
        if org_lower:
            low_set.add(org_lower)
    for extra in extra_low_impact:
        if isinstance(extra, str) and extra.strip():
            low_set.add(extra.strip().lower())
    if cat_lower in low_set:
        return Impact.LOW
    return Impact.MEDIUM


def _classify_title(title: str, keyword_map: dict[str, str]) -> str | None:
    t = title.lower()
    for kw, cat in keyword_map.items():
        if kw in t:
            return cat
    return None


def _client_from_participants(
    participants: Iterable[str], internal_domains: set[str]
) -> str | None:
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
    organization_label: str | None = None,
) -> list[TimeEntry]:
    """Aggregate blocks into TimeEntry rows by (label, category).

    ``tz`` controls which calendar day a block is attributed to in
    ``daily_hours``. Defaults to the system local timezone.

    ``organization_label`` is the user's own org name (derived from their
    sign-in domain, e.g. ``"Microsoft"``). Categories matching it default
    to :attr:`Impact.LOW` alongside the built-in ``Internal``/``Admin``
    buckets.
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
                impact=default_impact_for_category(category, organization_label=organization_label),
                source_block_ids=[b.id for b in group if b.id is not None],
                daily_hours={k: round(v, 2) for k, v in daily.items()},
            )
        )

    entries.sort(key=lambda e: e.duration_hours, reverse=True)
    return entries
