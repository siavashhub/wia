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
    label: str | None = None,
    high_impact_keywords: Iterable[str] = (),
) -> Impact:
    """Return the default :class:`Impact` for an entry with ``category``.

    - If ``label`` contains any of ``high_impact_keywords`` (case-insensitive
      substring match), the result is :attr:`Impact.HIGH` — this takes
      precedence over the category-based default below.
    - ``Internal`` and ``Admin`` (case-insensitive) → :attr:`Impact.LOW`.
    - The user's organization label (e.g. ``"Microsoft"``) → :attr:`Impact.LOW`.
    - Anything else → :attr:`Impact.MEDIUM`.
    """
    if label and high_impact_keywords:
        haystack = label.lower()
        for kw in high_impact_keywords:
            if isinstance(kw, str):
                needle = kw.strip().lower()
                if needle and needle in haystack:
                    return Impact.HIGH
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
    """Pick a category label from external (non-internal) participant domains.

    *Any* external participant wins, even if internal attendees outnumber
    them — a customer meeting with 10 Microsoft people and 1 customer
    representative is still a customer meeting. When multiple external
    domains are present, the most frequent wins.
    """
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


def _outlook_category_hint(block: ActivityBlock) -> str | None:
    """Return the first Outlook calendar category set on ``block`` (display
    casing), or ``None`` if the block has no categories.

    The Work IQ MCP client stores Outlook categories in two metadata
    fields: ``categories`` (lowercase, ``|``-joined, used for matching)
    and ``categories_display`` (original casing, ``", "``-joined, used
    here so the UI shows the user's chosen capitalisation).
    """
    display = (block.metadata.get("categories_display") or "").strip()
    if display:
        return display.split(",")[0].strip() or None
    raw = (block.metadata.get("categories") or "").strip()
    if raw:
        return raw.split("|")[0].strip().title() or None
    return None


def categorize(
    block: ActivityBlock,
    *,
    keyword_map: dict[str, str] | None = None,
    internal_domains: set[str] | None = None,
) -> tuple[str, str | None]:
    """Return ``(label, category)`` for a block.

    Precedence (highest first):

    1. Synthetic gap-fill (``Source.INFERRED``) → ``Admin``.
    2. User-set Outlook calendar category — the strongest signal of intent.
    3. External participant domain → derived client name.
    4. Title keyword map (sprint/standup/interview/...).
    5. ``Other`` — no usable signal.

    ``internal_domains`` lets the caller mark which email domains belong
    to the user's own organisation so they don't get treated as a
    customer. Typically derived from the signed-in UPN domain (e.g.
    ``{"microsoft.com"}``).
    """
    keyword_map = keyword_map or DEFAULT_KEYWORD_MAP
    internal_domains = internal_domains or set()

    if block.source is Source.INFERRED:
        title = block.title or "Inferred"
        return title, "Admin"

    title = block.title or "Untitled"

    # (2) User-set Outlook category wins outright when present. This lets
    # the user pin a calendar event to a category that the heuristics
    # would never have picked (e.g. an internal-only event tagged
    # "Customer" because it's prep work for a customer engagement).
    category = _outlook_category_hint(block)

    if category is None:
        # (3) Client from external participants.
        category = _client_from_participants(block.participants, internal_domains)

    if category is None:
        # (4) Title keyword fallback (sprint/standup/...).
        category = _classify_title(title, keyword_map)

    if category is None:
        # (5) Nothing matched — bucket under "Other" rather than the
        # historical "Internal" so genuine internal work is distinguishable
        # from "we don't know".
        category = "Other"

    label = f"{category} – {title}" if category and category not in title else title
    return label, category


def aggregate_entries(
    blocks: list[ActivityBlock],
    *,
    keyword_map: dict[str, str] | None = None,
    internal_domains: set[str] | None = None,
    tz: tzinfo | None = None,
    organization_label: str | None = None,
    high_impact_keywords: Iterable[str] = (),
    high_impact_categories: Iterable[str] = (),
) -> list[TimeEntry]:
    """Aggregate blocks into TimeEntry rows by (label, category).

    ``tz`` controls which calendar day a block is attributed to in
    ``daily_hours``. Defaults to the system local timezone.

    ``internal_domains`` is the set of email domains that belong to the
    user's own organisation. Blocks whose participants are *only* from
    these domains will not be assigned a "client" category (see
    :func:`_client_from_participants`).

    ``organization_label`` is the user's own org name (derived from their
    sign-in domain, e.g. ``"Microsoft"``). Categories matching it default
    to :attr:`Impact.LOW` alongside the built-in ``Internal``/``Admin``
    buckets.

    ``high_impact_keywords`` is a list of user-defined substrings that, when
    found (case-insensitive) in an entry's label or any constituent block
    title, force the entry's default impact to :attr:`Impact.HIGH`.

    ``high_impact_categories`` is a list of Outlook calendar category names
    that, when found on any constituent calendar block, force the entry's
    default impact to :attr:`Impact.HIGH`. Matching is case-insensitive
    against the ``categories`` block metadata written by the Work IQ MCP
    client (a ``|``-joined lowercase string).
    """
    if tz is None:
        tz = datetime.now().astimezone().tzinfo
    bucket: dict[tuple[str, str | None], list[ActivityBlock]] = defaultdict(list)
    for b in blocks:
        key = categorize(b, keyword_map=keyword_map, internal_domains=internal_domains)
        bucket[key].append(b)

    hi_kw_list = [
        kw.strip().lower()
        for kw in (high_impact_keywords or ())
        if isinstance(kw, str) and kw.strip()
    ]
    hi_cat_set = {
        c.strip().lower()
        for c in (high_impact_categories or ())
        if isinstance(c, str) and c.strip()
    }

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
        # Build the haystack used for keyword-based impact promotion: the
        # entry's label plus every block title in the group. This catches
        # cases where the keyword shows up in a constituent meeting title
        # but didn't make it into the rolled-up label.
        haystack_parts: list[str] = [label]
        for b in group:
            if b.title:
                haystack_parts.append(b.title)
        haystack = "\n".join(haystack_parts)
        impact = default_impact_for_category(
            category,
            organization_label=organization_label,
            label=haystack,
            high_impact_keywords=hi_kw_list,
        )
        # Promote to HIGH if any constituent calendar block carries an
        # Outlook category the user has flagged as high-impact. Mirrors
        # the keyword-based promotion above.
        if impact is not Impact.HIGH and hi_cat_set:
            for b in group:
                if b.source is not Source.CALENDAR:
                    continue
                raw_cats = b.metadata.get("categories", "")
                if not raw_cats:
                    continue
                if any(part for part in raw_cats.split("|") if part in hi_cat_set):
                    impact = Impact.HIGH
                    break
        entries.append(
            TimeEntry(
                label=label,
                category=category,
                duration_hours=round(hours, 2),
                confidence=conf,
                impact=impact,
                source_block_ids=[b.id for b in group if b.id is not None],
                daily_hours={k: round(v, 2) for k, v in daily.items()},
            )
        )

    entries.sort(key=lambda e: e.duration_hours, reverse=True)
    return entries
