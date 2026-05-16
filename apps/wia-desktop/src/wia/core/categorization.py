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


def _is_internal_only_meeting(participants: Iterable[str], internal_domains: set[str]) -> bool:
    """True when the event has at least one participant and every parseable
    attendee domain belongs to the user's own organisation.

    This is the "all-hands / team sync / internal workshop" signal: no
    Outlook tag, no external client to point at, but a clear roster of
    org-internal attendees. Without this we'd dump every such event into
    ``Other`` and lose the user's ``Internal`` bucket entirely.

    Events with no participants at all return ``False`` — those are
    appointment-style blocks (focus time, reminders) and belong under
    ``Other`` or whatever the title keyword map matches.
    """
    if not internal_domains:
        return False
    seen_any = False
    for email in participants:
        m = re.search(r"@([^>\s]+)", email)
        if not m:
            continue
        seen_any = True
        if m.group(1).lower() not in internal_domains:
            return False
    return seen_any


def _has_external_participant(participants: Iterable[str], internal_domains: set[str]) -> bool:
    """True when at least one parseable participant belongs to a domain
    *outside* ``internal_domains``.

    Distinct from :func:`_is_internal_only_meeting`: an event with no
    participants at all returns ``False`` here (no external attendees
    were seen), which is what the step (2) Outlook-tag collapse uses
    to also catch appointment-style blocks with an Outlook category
    but no attendees.

    Returns ``True`` conservatively when ``internal_domains`` is empty,
    so the caller doesn't collapse tags in the (rare) case where we
    can't classify any domain yet.
    """
    if not internal_domains:
        return True
    for email in participants:
        m = re.search(r"@([^>\s]+)", email)
        if not m:
            continue
        if m.group(1).lower() not in internal_domains:
            return True
    return False


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


# --- Umbrella-category title extraction --------------------------------------
# Some Outlook categories are *umbrella* tags (e.g. ``Customer``) that the
# user applies to every customer-facing event regardless of which customer
# it is. Categorising every one of those into a single ``Customer`` bucket
# defeats the purpose of grouping. When the Outlook tag is in the user's
# umbrella set we instead pull the specific customer / project code out of
# the event title (which the user typically prefixes, e.g. ``"Contoso- Azure Landing Zone"``).

_TITLE_SPLIT_RE = re.compile(r"\s*[-\u2013\u2014:|]\s*")

# Lowercase tokens that are recurrence / shape labels rather than customer
# names. When the first title segment matches one of these we advance to
# the next segment so ``"Weekly - Contososync"`` extracts ``Contososync``.
_TITLE_STOPWORDS: frozenset[str] = frozenset(
    {
        "weekly",
        "daily",
        "monthly",
        "biweekly",
        "bi-weekly",
        "sync",
        "standup",
        "stand-up",
        "review",
        "prep",
        "focus",
        "meeting",
        "call",
        "planning",
        "intro",
        "kickoff",
        "kick-off",
        "1:1",
        "check-in",
        "checkin",
        "catchup",
        "catch-up",
        "office hours",
    }
)

# Reject segments longer than this many characters as "probably a full
# sentence", not a customer code.
_MAX_DERIVED_CATEGORY_LEN = 24


def _extract_category_from_title(title: str) -> str | None:
    """Pull a customer / project code out of a structured event title.

    Returns the first non-stopword segment when the title is shaped like
    ``"<code> - <description>"`` (or ``\u2013`` / ``\u2014`` / ``:`` /
    ``|``-separated). Returns ``None`` for free-form titles with no
    separator, segments longer than :data:`_MAX_DERIVED_CATEGORY_LEN`,
    or titles whose every segment is a recurrence stopword.
    """
    if not title:
        return None
    segments = [s.strip() for s in _TITLE_SPLIT_RE.split(title) if s.strip()]
    if len(segments) < 2:
        return None
    for seg in segments:
        if seg.lower() in _TITLE_STOPWORDS:
            continue
        if len(seg) > _MAX_DERIVED_CATEGORY_LEN:
            continue
        return seg
    return None


def categorize(
    block: ActivityBlock,
    *,
    keyword_map: dict[str, str] | None = None,
    internal_domains: set[str] | None = None,
    umbrella_categories: Iterable[str] | None = None,
    preserve_categories: Iterable[str] | None = None,
) -> tuple[str, str | None]:
    """Return ``(label, category)`` for a block.

    Precedence (highest first):

    1. Synthetic gap-fill (``Source.INFERRED``) \u2192 ``Admin``.
    2. User-set Outlook calendar category \u2014 the strongest signal of intent.
       When the tag is in ``umbrella_categories`` (e.g. ``Customer``) we
       derive a *more specific* category from the title prefix; the raw
       umbrella name is only used as a last-resort fallback so a generic
       ``Customer`` tag doesn't collapse every customer into one bucket.
       When the meeting has no external attendees (either internal-only
       or an appointment-style block with no attendees at all) and the
       tag is NOT in ``preserve_categories``, the tag is replaced with
       ``Internal`` \u2014 this keeps generic organising tags like
       ``Workshop`` / ``Service`` / ``Messages`` from creating one-off
       buckets. Tags listed in ``preserve_categories`` always pass
       through verbatim.
    3. External participant domain \u2192 derived client name.
    4. Title keyword map (sprint/standup/interview/...).
    5. All-internal participants → ``Internal`` (all-hands, team syncs,
       internal workshops).
    6. ``Other`` — no usable signal.

    ``internal_domains`` lets the caller mark which email domains belong
    to the user's own organisation so they don't get treated as a
    customer. Typically derived from the signed-in UPN domain (e.g.
    ``{"microsoft.com"}``).

    ``umbrella_categories`` is the user-configured list of Outlook tags
    that should trigger title-based extraction rather than being used
    1:1. See :data:`wia.api.prefs.DEFAULT_UMBRELLA_CATEGORIES` for the
    out-of-the-box defaults.

    ``preserve_categories`` is the user-configured list of Outlook tags
    that should *always* be kept verbatim, even on internal-only
    meetings. Use it to opt specific internal tracks (e.g. ``Design``,
    ``Recruiting``) out of the default internal-only → ``Internal``
    collapse.
    """
    keyword_map = keyword_map or DEFAULT_KEYWORD_MAP
    internal_domains = internal_domains or set()
    umbrella_set = {c.strip().lower() for c in (umbrella_categories or ()) if c}
    preserve_set = {c.strip().lower() for c in (preserve_categories or ()) if c}

    if block.source is Source.INFERRED:
        title = block.title or "Inferred"
        return title, "Admin"

    title = block.title or "Untitled"

    # (2) User-set Outlook category wins outright when present. This lets
    # the user pin a calendar event to a category that the heuristics
    # would never have picked (e.g. an internal-only event tagged
    # "Customer" because it's prep work for a customer engagement).
    category = _outlook_category_hint(block)

    if category is not None and category.strip().lower() in umbrella_set:
        # Umbrella tag \u2014 try to extract a specific category from the
        # title; fall back to an external-participant-derived name; only
        # then surrender to the generic umbrella name.
        derived = _extract_category_from_title(title)
        if derived is None:
            derived = _client_from_participants(block.participants, internal_domains)
        if derived:
            category = derived
        # else: keep ``category`` as the umbrella name (better than "Other").
    elif (
        category is not None
        and category.strip().lower() not in preserve_set
        and not _has_external_participant(block.participants, internal_domains)
    ):
        # Outlook tag on a meeting with no external attendees — either
        # internal-only or an appointment-style block with no attendees
        # at all. Collapse to ``Internal`` by default so generic
        # organising tags like ``Workshop`` / ``Service`` /
        # ``Messages`` don't spawn one-off buckets. The user can opt
        # specific tags out via the ``preserve_calendar_categories``
        # pref.
        category = "Internal"

    if category is None:
        # (3) Client from external participants.
        category = _client_from_participants(block.participants, internal_domains)

    if category is None:
        # (4) Title keyword fallback (sprint/standup/...).
        category = _classify_title(title, keyword_map)

    if category is None and _is_internal_only_meeting(block.participants, internal_domains):
        # (5) All attendees are from the user's own org — clear
        # internal-meeting signal. Catches all-hands, team syncs,
        # internal workshops that don't trip the keyword map.
        category = "Internal"

    if category is None:
        # (6) Nothing matched — bucket under "Other" rather than the
        # historical "Internal" so genuine internal work is distinguishable
        # from "we don't know".
        category = "Other"

    label = f"{category} – {title}" if category and category.lower() not in title.lower() else title
    return label, category


def _collect_sources(group: list[ActivityBlock]) -> list[str]:
    """Return the deduped sorted set of signal sources behind ``group``.

    Includes both each block's primary ``source`` and any extras recorded in
    ``metadata["merged_sources"]`` by :func:`dedup_across_sources` — that way
    a meeting that was deduped from Teams/email into a Calendar block still
    shows the Teams/email provenance tag in the Briefing UI.
    """
    sources: set[str] = set()
    for b in group:
        sources.add(b.source.value)
        extras = b.metadata.get("merged_sources", "")
        if extras:
            sources.update(s for s in extras.split(",") if s)
    return sorted(sources)


# --- Read-time fallback for entries that pre-date the ``sources`` column ---
_EMAIL_PREFIX_RE = re.compile(r"^\s*(re|fw|fwd)\s*:", re.IGNORECASE)
_CHAT_RE = re.compile(r"\bchat with\b", re.IGNORECASE)


def infer_sources_from_label(label: str | None, category: str | None = None) -> list[str]:
    """Best-effort guess of an entry's signal sources from its label.

    Rows persisted before WIA tracked ``sources`` carry no provenance tags.
    Rather than show an empty cell in the Briefing UI we apply a small,
    conservative heuristic so the user always sees *something*. A real
    rescan overwrites the guess with the actual deduped source set.

    Rules (checked in order):

    - ``Re:`` / ``Fw:`` / ``Fwd:`` prefix → ``["email"]``
    - contains ``Chat with …``           → ``["teams"]``
    - otherwise                          → ``["unknown"]``

    The ``unknown`` placeholder is deliberately distinct from a real source
    so the UI can style it as a low-confidence hint and so a future rescan
    will always replace it.
    """
    # Strip any "Category - " prefix added by ``categorize``; the heuristic
    # should match the original event title, not the bucket name.
    text = (label or "").strip()
    if " – " in text:
        text = text.split(" – ", 1)[1].strip()
    if not text and not (category or "").strip():
        return []
    if _EMAIL_PREFIX_RE.search(text):
        return ["email"]
    if _CHAT_RE.search(text):
        return ["teams"]
    return ["unknown"]


def aggregate_entries(
    blocks: list[ActivityBlock],
    *,
    keyword_map: dict[str, str] | None = None,
    internal_domains: set[str] | None = None,
    tz: tzinfo | None = None,
    organization_label: str | None = None,
    high_impact_keywords: Iterable[str] = (),
    high_impact_categories: Iterable[str] = (),
    umbrella_categories: Iterable[str] = (),
    preserve_categories: Iterable[str] = (),
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
        key = categorize(
            b,
            keyword_map=keyword_map,
            internal_domains=internal_domains,
            umbrella_categories=umbrella_categories,
            preserve_categories=preserve_categories,
        )
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
                sources=_collect_sources(group),
            )
        )

    entries.sort(key=lambda e: e.duration_hours, reverse=True)
    return entries
