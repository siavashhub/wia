"""Briefing orchestrator — fetches signals, builds blocks/entries, persists."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from datetime import UTC, date, datetime

from wia.core.categorization import aggregate_entries
from wia.core.grouping import fill_gaps, merge_blocks
from wia.core.types import (
    ActivityBlock,
    Briefing,
    BriefingTotals,
    Confidence,
    Source,
    TimeEntry,
    WorkAreaSummary,
)
from wia.core.week import week_bounds, week_days
from wia.mcp_clients.workiq import get_workiq_client
from wia.storage import entries as entries_repo

log = logging.getLogger(__name__)


def _totals(blocks: list[ActivityBlock]) -> BriefingTotals:
    meetings = sum(b.duration_hours for b in blocks if b.source is Source.CALENDAR)
    focus = sum(
        b.duration_hours
        for b in blocks
        if b.source is Source.INFERRED and (b.title or "").lower().startswith("focus")
    )
    collab = sum(b.duration_hours for b in blocks if b.source in {Source.TEAMS, Source.EMAIL})
    total = sum(b.duration_hours for b in blocks)
    return BriefingTotals(
        total_hours=round(total, 2),
        meetings_hours=round(meetings, 2),
        focus_hours=round(focus, 2),
        collaboration_hours=round(collab, 2),
    )


def _top_work_areas(entries: list[TimeEntry], limit: int = 5) -> list[WorkAreaSummary]:
    by_cat: dict[str, float] = defaultdict(float)
    for e in entries:
        by_cat[e.category or "Uncategorized"] += e.duration_hours
    items = sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [WorkAreaSummary(label=k, hours=round(v, 2)) for k, v in items]


def _matches_excluded(block: ActivityBlock, keywords_lower: list[str]) -> bool:
    """Return True if any keyword (already lower-cased) is a substring of
    the block's title or any participant identifier.

    Inferred / gap-fill blocks are produced by WIA itself and have no
    "real" subject — we never filter them out, so an exclusion rule
    can't accidentally drop synthetic Admin/Focus time.
    """
    if block.source is Source.INFERRED:
        return False
    haystack = (block.title or "").lower()
    if any(kw in haystack for kw in keywords_lower):
        return True
    for p in block.participants:
        p_lower = p.lower()
        if any(kw in p_lower for kw in keywords_lower):
            return True
    return False


def _matches_excluded_category(block: ActivityBlock, categories_lower: set[str]) -> bool:
    """Return True if the calendar block carries any Outlook category that
    the user has chosen to exclude. Matches the metadata written by
    ``mcp_clients.workiq._event_to_block`` (``categories`` is a
    ``|``-joined lowercase string).
    """
    if block.source is not Source.CALENDAR:
        return False
    raw = block.metadata.get("categories", "")
    if not raw:
        return False
    return any(part for part in raw.split("|") if part in categories_lower)


def _is_private_meeting(block: ActivityBlock) -> bool:
    """True when a calendar block is marked as private/personal/confidential.

    Microsoft Copilot is inconsistent about returning the ``sensitivity``
    field even when explicitly asked, so we also fall back to a few
    well-known title patterns Outlook uses when an event is marked
    Private (the body and attendees get redacted but the subject often
    survives as ``"Private appointment"`` or starts with ``"Private:"``).
    """
    # Imported lazily to avoid a circular import at module load time.
    from wia.api.prefs import PRIVATE_SENSITIVITIES

    if block.source is not Source.CALENDAR:
        return False
    sensitivity = (block.metadata.get("sensitivity") or "").lower()
    if sensitivity in PRIVATE_SENSITIVITIES:
        return True
    if (block.metadata.get("is_private") or "").lower() in {"1", "true", "yes"}:
        return True
    title = (block.title or "").strip().lower()
    if not title:
        return False
    # Common Outlook / Copilot fallbacks when the body is redacted.
    private_titles = {
        "private",
        "private appointment",
        "private event",
        "personal",
        "personal appointment",
        "confidential",
    }
    if title in private_titles:
        return True
    private_prefixes = ("private:", "private -", "personal:", "personal -", "confidential:")
    return title.startswith(private_prefixes)


_EMAIL_DOMAIN_RE = re.compile(r"@([^>\s]+)")


def _derive_organization_from_blocks(blocks: list[ActivityBlock]) -> str | None:
    """Guess the user's organization label from observed participant emails.

    Picks the most common email domain across all blocks (the user's own
    organization is overwhelmingly the most-seen domain in their meeting
    invites) and converts it to a human label via
    :func:`wia.api.prefs.derive_organization_label_from_domain`. Returns
    ``None`` when there is no participant data to work from.
    """
    from wia.api.prefs import derive_organization_label_from_domain

    counts: dict[str, int] = defaultdict(int)
    for b in blocks:
        for raw in b.participants:
            m = _EMAIL_DOMAIN_RE.search(raw or "")
            if not m:
                continue
            counts[m.group(1).lower()] += 1
    if not counts:
        return None
    top_domain = max(counts.items(), key=lambda kv: kv[1])[0]
    return derive_organization_label_from_domain(top_domain) or None


async def build_briefing(
    *,
    week_of: date | None = None,
    refresh: bool = False,
    signals: list[str] | None = None,
) -> Briefing:
    monday, sunday = week_bounds(week_of)
    week_iso = monday.isoformat()
    log.info("Building briefing for week %s..%s (refresh=%s)", monday, sunday, refresh)

    # 0. Cache short-circuit: when the caller did not ask for a refresh we
    # never contact Work IQ. If we have cached entries for this week we
    # return them; otherwise we return an empty "no-signals" briefing so
    # the UI can show the empty state and let the user opt in to a scan.
    # This prevents week navigation (Prev/Next) from silently triggering
    # an MCP scan against Work IQ for weeks that have never been scanned.
    if not refresh:
        cached = entries_repo.list_entries(week_of=week_iso)
        if cached:
            log.info("Using cached briefing for %s (%d entries)", week_iso, len(cached))
            return Briefing(
                week_start=monday.isoformat(),
                week_end=sunday.isoformat(),
                totals=_totals_from_entries(cached),
                top_work_areas=_top_work_areas(cached),
                entries=cached,
                blocks=[],
                generated_at=datetime.now(UTC),
                status="ok",
            )
        log.info("No cached briefing for %s; skipping Work IQ scan (refresh=False)", week_iso)
        return Briefing(
            week_start=monday.isoformat(),
            week_end=sunday.isoformat(),
            totals=BriefingTotals(
                total_hours=0, meetings_hours=0, focus_hours=0, collaboration_hours=0
            ),
            top_work_areas=[],
            entries=[],
            blocks=[],
            generated_at=datetime.now(UTC),
            status="no-signals",
        )

    # Determine which signals to pull. Default to user prefs.
    if signals is None:
        # Imported here to avoid a circular import at module load time.
        from wia.api.prefs import get_enabled_signals

        signals = get_enabled_signals()
    log.info("Scanning enabled signals: %s", signals)

    # Excluded keywords: case-insensitive substring match against block
    # title and participants. Drives off the same prefs row the UI edits.
    from wia.api.prefs import (
        get_exclude_private_meetings,
        get_excluded_calendar_categories,
        get_excluded_keywords,
        get_high_impact_keywords,
        get_organization_label,
        is_organization_auto,
        set_organization_label,
    )

    excluded_keywords = [kw.lower() for kw in get_excluded_keywords() if kw.strip()]
    if excluded_keywords:
        log.info("Excluding blocks matching keywords: %s", excluded_keywords)
    excluded_categories = {c.lower() for c in get_excluded_calendar_categories() if c.strip()}
    if excluded_categories:
        log.info(
            "Excluding calendar blocks tagged with categories: %s", sorted(excluded_categories)
        )
    exclude_private = get_exclude_private_meetings()
    if exclude_private:
        log.info("Excluding private/personal/confidential calendar meetings")

    # 1. Fetch enabled signals from Work IQ MCP, in parallel.
    client = get_workiq_client()
    coros: list = []
    kinds: list[str] = []
    if "calendar" in signals:
        coros.append(client.fetch_calendar_blocks(monday, sunday))
        kinds.append("calendar")
    if "teams" in signals:
        coros.append(client.fetch_teams_blocks(monday, sunday))
        kinds.append("teams")
    if "email" in signals:
        coros.append(client.fetch_email_blocks(monday, sunday))
        kinds.append("email")

    if not coros:
        # User disabled every signal — nothing to scan, return empty briefing.
        return Briefing(
            week_start=monday.isoformat(),
            week_end=sunday.isoformat(),
            totals=BriefingTotals(
                total_hours=0, meetings_hours=0, focus_hours=0, collaboration_hours=0
            ),
            top_work_areas=[],
            entries=[],
            blocks=[],
            generated_at=datetime.now(UTC),
            status="no-signals",
        )

    raw_blocks: list[ActivityBlock] = []
    workiq_failed = False
    results = await asyncio.gather(*coros, return_exceptions=True)
    for kind, res in zip(kinds, results, strict=True):
        if isinstance(res, Exception):
            log.warning("Work IQ %s fetch failed: %s", kind, res)
            workiq_failed = True
            continue
        raw_blocks.extend(res)

    if excluded_keywords and raw_blocks:
        before = len(raw_blocks)
        raw_blocks = [b for b in raw_blocks if not _matches_excluded(b, excluded_keywords)]
        dropped = before - len(raw_blocks)
        if dropped:
            log.info("Excluded %d/%d block(s) by keyword filter", dropped, before)

    if excluded_categories and raw_blocks:
        before = len(raw_blocks)
        raw_blocks = [
            b for b in raw_blocks if not _matches_excluded_category(b, excluded_categories)
        ]
        dropped = before - len(raw_blocks)
        if dropped:
            log.info("Excluded %d/%d calendar block(s) by category filter", dropped, before)

    if exclude_private and raw_blocks:
        before = len(raw_blocks)
        raw_blocks = [b for b in raw_blocks if not _is_private_meeting(b)]
        dropped = before - len(raw_blocks)
        if dropped:
            log.info("Excluded %d/%d private calendar meeting(s)", dropped, before)

    if workiq_failed and not raw_blocks:
        return Briefing(
            week_start=monday.isoformat(),
            week_end=sunday.isoformat(),
            totals=BriefingTotals(
                total_hours=0, meetings_hours=0, focus_hours=0, collaboration_hours=0
            ),
            top_work_areas=[],
            entries=[],
            blocks=[],
            generated_at=datetime.now(UTC),
            status="workiq-not-enabled",
        )

    # 2. Group + (only if we have real signals) fill gaps.
    # When Work IQ returns zero events we deliberately skip gap-filling so
    # we don't synthesize 40 fake hours of "Admin" for an empty week.
    # Gap-filling only runs on weekdays — we don't want to synthesize
    # phantom "Focus time" on Saturday and Sunday.
    merged = merge_blocks(raw_blocks)
    if merged:
        days = [d for d in week_days(monday) if d.weekday() < 5]
        all_blocks = fill_gaps(merged, days)
    else:
        all_blocks = []

    # Auto-derive the user's organization label from the most common
    # participant email domain so default Impact assignment knows which
    # categories to mark as Low. Only writes when the user has not
    # explicitly set one (or has only an auto-derived one we can refine).
    organization_label = get_organization_label()
    if (not organization_label or is_organization_auto()) and raw_blocks:
        derived = _derive_organization_from_blocks(raw_blocks)
        if derived and derived != organization_label:
            set_organization_label(derived, auto=True)
            organization_label = derived

    # 3. Categorize → entries
    entries = aggregate_entries(
        all_blocks,
        organization_label=organization_label or None,
        high_impact_keywords=get_high_impact_keywords(),
    )
    for e in entries:
        e.week_of = week_iso

    # 4. Persist (replace existing for this week unless user has manual edits)
    entries_repo.replace_week(week_iso, entries)
    entries = entries_repo.list_entries(week_of=week_iso)

    return Briefing(
        week_start=monday.isoformat(),
        week_end=sunday.isoformat(),
        totals=_totals(all_blocks),
        top_work_areas=_top_work_areas(entries),
        entries=entries,
        blocks=all_blocks,
        generated_at=datetime.now(UTC),
        status="ok" if all_blocks else "no-signals",
    )


def _totals_from_entries(entries: list[TimeEntry]) -> BriefingTotals:
    """Approximate totals when we don't have live blocks (cache path).

    Confidence is the proxy for source (we don't persist source on
    ``TimeEntry`` rows):

    - ``HIGH`` → real calendar meetings.
    - ``MEDIUM`` → Teams / email collaboration signals (or any entry
      whose constituents include a Teams/email block, since
      ``aggregate_entries`` keeps the lowest constituent confidence).
    - ``LOW`` → inferred gap-fill (Admin / Focus). Focus entries are
      additionally identified by label.
    """
    meetings = sum(e.duration_hours for e in entries if e.confidence is Confidence.HIGH)
    collab = sum(e.duration_hours for e in entries if e.confidence is Confidence.MEDIUM)
    focus = sum(e.duration_hours for e in entries if (e.label or "").lower().startswith("focus"))
    total = sum(e.duration_hours for e in entries)
    return BriefingTotals(
        total_hours=round(total, 2),
        meetings_hours=round(meetings, 2),
        focus_hours=round(focus, 2),
        collaboration_hours=round(collab, 2),
    )
