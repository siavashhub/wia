"""User preferences endpoints (theme, signal selection, etc.)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from wia.storage import prefs as prefs_store

router = APIRouter()

ALLOWED_THEMES = {"light", "dark", "system"}
ALLOWED_SIGNALS = ("calendar", "teams", "email")
ALLOWED_WEEK_STARTS = {"mon", "sun"}
DEFAULT_SIGNALS = ["calendar"]
DEFAULT_WEEK_STARTS_ON = "sun"
PREF_THEME = "theme"
PREF_SIGNALS = "enabled_signals"
PREF_EXCLUDED_KEYWORDS = "excluded_keywords"
PREF_WEEK_STARTS_ON = "week_starts_on"
PREF_EXCLUDED_CATEGORIES = "excluded_calendar_categories"
PREF_HIGH_IMPACT_KEYWORDS = "high_impact_keywords"
PREF_HIGH_IMPACT_CATEGORIES = "high_impact_calendar_categories"
PREF_UMBRELLA_CATEGORIES = "umbrella_calendar_categories"
PREF_PRESERVE_CATEGORIES = "preserve_calendar_categories"
PREF_EXCLUDE_PRIVATE = "exclude_private_meetings"
PREF_ORGANIZATION = "organization_label"
PREF_ORGANIZATION_AUTO = "organization_label_auto"  # 1 if value was auto-derived
PREF_USER_UPN = "user_upn"
PREF_USER_DISPLAY_NAME = "user_display_name"

# Sensitivity values (Outlook) considered "private" for the toggle.
PRIVATE_SENSITIVITIES = frozenset({"private", "personal", "confidential"})

# Cap the list so a runaway UI can't bloat the prefs row or slow down the
# substring filter the orchestrator runs against every fetched block.
MAX_EXCLUDED_KEYWORDS = 100
MAX_KEYWORD_LENGTH = 100
MAX_EXCLUDED_CATEGORIES = 100
MAX_CATEGORY_LENGTH = 100
MAX_HIGH_IMPACT_KEYWORDS = 100
MAX_HIGH_IMPACT_KEYWORD_LENGTH = 100
MAX_HIGH_IMPACT_CATEGORIES = 100
MAX_HIGH_IMPACT_CATEGORY_LENGTH = 100
MAX_UMBRELLA_CATEGORIES = 100
MAX_UMBRELLA_CATEGORY_LENGTH = 100
MAX_PRESERVE_CATEGORIES = 100
MAX_PRESERVE_CATEGORY_LENGTH = 100
MAX_ORGANIZATION_LENGTH = 100

# Outlook calendar categories treated as "umbrella" tags — the categoriser
# uses them as a *signal* that an event belongs in a customer/client/vendor
# bucket but derives the *specific* category from the event title (e.g.
# ``Contoso- Azure Landing Zone vWAN`` under the umbrella ``Customer`` becomes a ``Contoso``
# entry, not a generic ``Customer`` bucket). Users can override via
# ``PUT /prefs``; an empty list means "no umbrellas, use Outlook tags 1:1".
DEFAULT_UMBRELLA_CATEGORIES: list[str] = [
    "Customer",
    "Client",
    "Vendor",
    "Partner",
    "Account",
]


def _read_signals() -> list[str]:
    raw = prefs_store.get_pref(PREF_SIGNALS)
    if not raw:
        return list(DEFAULT_SIGNALS)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return list(DEFAULT_SIGNALS)
    if not isinstance(parsed, list):
        return list(DEFAULT_SIGNALS)
    cleaned = [s for s in parsed if isinstance(s, str) and s in ALLOWED_SIGNALS]
    return cleaned or list(DEFAULT_SIGNALS)


def _read_excluded_keywords() -> list[str]:
    raw = prefs_store.get_pref(PREF_EXCLUDED_KEYWORDS)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for kw in parsed:
        if not isinstance(kw, str):
            continue
        cleaned = kw.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _normalize_keywords(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise HTTPException(status_code=400, detail="excluded_keywords must all be strings")
        cleaned = raw.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_KEYWORD_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"keyword exceeds {MAX_KEYWORD_LENGTH} chars: {cleaned[:32]!r}…",
            )
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    if len(out) > MAX_EXCLUDED_KEYWORDS:
        raise HTTPException(
            status_code=400,
            detail=f"at most {MAX_EXCLUDED_KEYWORDS} excluded keywords allowed",
        )
    return out


def get_enabled_signals() -> list[str]:
    """Public helper used by the orchestrator to know which signals to pull."""
    return _read_signals()


def get_excluded_keywords() -> list[str]:
    """Public helper used by the orchestrator to filter fetched blocks."""
    return _read_excluded_keywords()


def _read_week_starts_on() -> str:
    raw = prefs_store.get_pref(PREF_WEEK_STARTS_ON)
    if raw in ALLOWED_WEEK_STARTS:
        return raw
    return DEFAULT_WEEK_STARTS_ON


def _read_excluded_categories() -> list[str]:
    raw = prefs_store.get_pref(PREF_EXCLUDED_CATEGORIES)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for c in parsed:
        if not isinstance(c, str):
            continue
        cleaned = c.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _normalize_categories(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise HTTPException(
                status_code=400, detail="excluded_calendar_categories must all be strings"
            )
        cleaned = raw.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_CATEGORY_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"category exceeds {MAX_CATEGORY_LENGTH} chars: {cleaned[:32]!r}…",
            )
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    if len(out) > MAX_EXCLUDED_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"at most {MAX_EXCLUDED_CATEGORIES} excluded categories allowed",
        )
    return out


def _read_exclude_private() -> bool:
    raw = prefs_store.get_pref(PREF_EXCLUDE_PRIVATE)
    if not raw:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_excluded_calendar_categories() -> list[str]:
    """Public helper used by the orchestrator to filter calendar blocks by
    Outlook category."""
    return _read_excluded_categories()


def _read_high_impact_keywords() -> list[str]:
    raw = prefs_store.get_pref(PREF_HIGH_IMPACT_KEYWORDS)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for kw in parsed:
        if not isinstance(kw, str):
            continue
        cleaned = kw.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _normalize_high_impact_keywords(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise HTTPException(status_code=400, detail="high_impact_keywords must all be strings")
        cleaned = raw.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_HIGH_IMPACT_KEYWORD_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"high-impact keyword exceeds {MAX_HIGH_IMPACT_KEYWORD_LENGTH} "
                    f"chars: {cleaned[:32]!r}…"
                ),
            )
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    if len(out) > MAX_HIGH_IMPACT_KEYWORDS:
        raise HTTPException(
            status_code=400,
            detail=f"at most {MAX_HIGH_IMPACT_KEYWORDS} high-impact keywords allowed",
        )
    return out


def get_high_impact_keywords() -> list[str]:
    """Public helper used by the orchestrator to promote matching entries to
    high impact during briefing aggregation."""
    return _read_high_impact_keywords()


def _read_high_impact_categories() -> list[str]:
    raw = prefs_store.get_pref(PREF_HIGH_IMPACT_CATEGORIES)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for c in parsed:
        if not isinstance(c, str):
            continue
        cleaned = c.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _normalize_high_impact_categories(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise HTTPException(
                status_code=400,
                detail="high_impact_calendar_categories must all be strings",
            )
        cleaned = raw.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_HIGH_IMPACT_CATEGORY_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"high-impact category exceeds {MAX_HIGH_IMPACT_CATEGORY_LENGTH} "
                    f"chars: {cleaned[:32]!r}…"
                ),
            )
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    if len(out) > MAX_HIGH_IMPACT_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"at most {MAX_HIGH_IMPACT_CATEGORIES} high-impact categories allowed",
        )
    return out


def get_high_impact_calendar_categories() -> list[str]:
    """Public helper used by the orchestrator to promote entries whose
    constituent calendar blocks carry any of these Outlook categories to
    high impact."""
    return _read_high_impact_categories()


def _read_umbrella_categories() -> list[str]:
    """Return the user-configured umbrella Outlook categories.

    Falls back to :data:`DEFAULT_UMBRELLA_CATEGORIES` when the pref has
    never been set so brand-new users get sensible behaviour. An
    explicit empty list (the user cleared the pref) is honoured and
    disables umbrella behaviour entirely.
    """
    raw = prefs_store.get_pref(PREF_UMBRELLA_CATEGORIES)
    if raw is None:
        return list(DEFAULT_UMBRELLA_CATEGORIES)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return list(DEFAULT_UMBRELLA_CATEGORIES)
    if not isinstance(parsed, list):
        return list(DEFAULT_UMBRELLA_CATEGORIES)
    out: list[str] = []
    seen: set[str] = set()
    for c in parsed:
        if not isinstance(c, str):
            continue
        cleaned = c.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _normalize_umbrella_categories(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise HTTPException(
                status_code=400,
                detail="umbrella_calendar_categories must all be strings",
            )
        cleaned = raw.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_UMBRELLA_CATEGORY_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"umbrella category exceeds {MAX_UMBRELLA_CATEGORY_LENGTH} "
                    f"chars: {cleaned[:32]!r}\u2026"
                ),
            )
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    if len(out) > MAX_UMBRELLA_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"at most {MAX_UMBRELLA_CATEGORIES} umbrella categories allowed",
        )
    return out


def get_umbrella_calendar_categories() -> list[str]:
    """Public helper used by the categoriser: Outlook category tags that
    should trigger title-based sub-categorisation rather than being used
    as the literal final category."""
    return _read_umbrella_categories()


# Outlook categories that should always pass through verbatim, even when
# the meeting is internal-only. By default WIA collapses any Outlook tag
# on an all-internal meeting into the ``Internal`` bucket (so generic
# organising tags like ``Workshop`` / ``Service`` don't bloat the
# category list). Adding a tag here opts it out of that collapse so it
# becomes its own first-class category again (e.g. an internal
# ``Design`` track the user wants to keep visible).
DEFAULT_PRESERVE_CATEGORIES: list[str] = []


def _read_preserve_categories() -> list[str]:
    """Return the user-configured tags that should bypass the
    internal-only → Internal collapse.

    Returns an empty list when the pref has never been set — the
    default is to collapse all Outlook tags on internal-only meetings
    into ``Internal``.
    """
    raw = prefs_store.get_pref(PREF_PRESERVE_CATEGORIES)
    if not raw:
        return list(DEFAULT_PRESERVE_CATEGORIES)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return list(DEFAULT_PRESERVE_CATEGORIES)
    if not isinstance(parsed, list):
        return list(DEFAULT_PRESERVE_CATEGORIES)
    out: list[str] = []
    seen: set[str] = set()
    for c in parsed:
        if not isinstance(c, str):
            continue
        cleaned = c.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _normalize_preserve_categories(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise HTTPException(
                status_code=400,
                detail="preserve_calendar_categories must all be strings",
            )
        cleaned = raw.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_PRESERVE_CATEGORY_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"preserve category exceeds {MAX_PRESERVE_CATEGORY_LENGTH} "
                    f"chars: {cleaned[:32]!r}\u2026"
                ),
            )
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    if len(out) > MAX_PRESERVE_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"at most {MAX_PRESERVE_CATEGORIES} preserve categories allowed",
        )
    return out


def get_preserve_calendar_categories() -> list[str]:
    """Public helper used by the categoriser: Outlook tags that should
    NOT be collapsed to ``Internal`` when the meeting is internal-only.
    Lets the user keep a few intentional internal tags as their own
    top-level category (e.g. ``Design``, ``Recruiting``)."""
    return _read_preserve_categories()


def get_exclude_private_meetings() -> bool:
    """Public helper: should calendar blocks marked private/personal/
    confidential be dropped before grouping?"""
    return _read_exclude_private()


def get_organization_label() -> str:
    """Public helper: the user's organization label (e.g. ``"Microsoft"``).

    Empty string when the user has not set / auto-derived one yet.
    """
    return (prefs_store.get_pref(PREF_ORGANIZATION) or "").strip()


def is_organization_auto() -> bool:
    """True when the stored organization label was auto-derived from observed
    participant domains (i.e. the user has not explicitly set one)."""
    raw = prefs_store.get_pref(PREF_ORGANIZATION_AUTO) or ""
    return raw.strip() in {"1", "true", "yes"}


def set_organization_label(label: str, *, auto: bool) -> None:
    """Persist the organization label and whether it was auto-derived."""
    cleaned = (label or "").strip()
    prefs_store.set_pref(PREF_ORGANIZATION, cleaned[:MAX_ORGANIZATION_LENGTH])
    prefs_store.set_pref(PREF_ORGANIZATION_AUTO, "1" if auto else "0")


def derive_organization_label_from_domain(domain: str) -> str:
    """Convert an email domain (``"microsoft.com"``) to a human label
    (``"Microsoft"``).

    Strips the TLD and any leading ``mail.`` / ``corp.`` style prefixes
    so ``corp.microsoft.com`` -> ``"Microsoft"``.
    """
    raw = (domain or "").strip().lower()
    if not raw:
        return ""
    parts = [p for p in raw.split(".") if p]
    # Drop common subdomain prefixes used for email routing.
    while parts and parts[0] in {"mail", "corp", "smtp", "exch", "outlook"}:
        parts = parts[1:]
    if not parts:
        return ""
    # The "head" piece is the org name; e.g. ``microsoft.com`` -> ``microsoft``.
    head = parts[0]
    return head.replace("-", " ").title()


def get_user_identity() -> tuple[str, str]:
    """Return the cached signed-in user's ``(upn, display_name)``.

    Empty strings when no identity has been fetched yet.
    """
    return (
        (prefs_store.get_pref(PREF_USER_UPN) or "").strip(),
        (prefs_store.get_pref(PREF_USER_DISPLAY_NAME) or "").strip(),
    )


def set_user_identity(upn: str, display_name: str | None) -> None:
    """Persist the signed-in user's UPN and display name."""
    prefs_store.set_pref(PREF_USER_UPN, (upn or "").strip()[:200])
    prefs_store.set_pref(PREF_USER_DISPLAY_NAME, (display_name or "").strip()[:200])


class Prefs(BaseModel):
    theme: str = "system"
    enabled_signals: list[str] = Field(default_factory=lambda: list(DEFAULT_SIGNALS))
    excluded_keywords: list[str] = Field(default_factory=list)
    week_starts_on: str = DEFAULT_WEEK_STARTS_ON
    excluded_calendar_categories: list[str] = Field(default_factory=list)
    high_impact_keywords: list[str] = Field(default_factory=list)
    high_impact_calendar_categories: list[str] = Field(default_factory=list)
    umbrella_calendar_categories: list[str] = Field(
        default_factory=lambda: list(DEFAULT_UMBRELLA_CATEGORIES)
    )
    preserve_calendar_categories: list[str] = Field(default_factory=list)
    exclude_private_meetings: bool = False
    organization_label: str = ""
    organization_label_auto: bool = False
    user_upn: str = ""
    user_display_name: str = ""


class PrefsUpdate(BaseModel):
    theme: str | None = None
    enabled_signals: list[str] | None = None
    excluded_keywords: list[str] | None = None
    week_starts_on: str | None = None
    excluded_calendar_categories: list[str] | None = None
    high_impact_keywords: list[str] | None = None
    high_impact_calendar_categories: list[str] | None = None
    umbrella_calendar_categories: list[str] | None = None
    preserve_calendar_categories: list[str] | None = None
    exclude_private_meetings: bool | None = None
    organization_label: str | None = None


@router.get("")
async def get_prefs() -> Prefs:
    upn, display = get_user_identity()
    return Prefs(
        theme=prefs_store.get_pref(PREF_THEME) or "system",
        enabled_signals=_read_signals(),
        excluded_keywords=_read_excluded_keywords(),
        week_starts_on=_read_week_starts_on(),
        excluded_calendar_categories=_read_excluded_categories(),
        high_impact_keywords=_read_high_impact_keywords(),
        high_impact_calendar_categories=_read_high_impact_categories(),
        umbrella_calendar_categories=_read_umbrella_categories(),
        preserve_calendar_categories=_read_preserve_categories(),
        exclude_private_meetings=_read_exclude_private(),
        organization_label=get_organization_label(),
        organization_label_auto=is_organization_auto(),
        user_upn=upn,
        user_display_name=display,
    )


@router.put("")
async def update_prefs(update: PrefsUpdate) -> Prefs:
    if update.theme is not None:
        if update.theme not in ALLOWED_THEMES:
            raise HTTPException(
                status_code=400,
                detail=f"theme must be one of {sorted(ALLOWED_THEMES)}",
            )
        prefs_store.set_pref(PREF_THEME, update.theme)
    if update.enabled_signals is not None:
        bad = [s for s in update.enabled_signals if s not in ALLOWED_SIGNALS]
        if bad:
            raise HTTPException(
                status_code=400,
                detail=f"invalid signals: {bad}; allowed={list(ALLOWED_SIGNALS)}",
            )
        # Always keep at least one signal so a scan has something to do.
        cleaned = list(dict.fromkeys(update.enabled_signals)) or list(DEFAULT_SIGNALS)
        prefs_store.set_pref(PREF_SIGNALS, json.dumps(cleaned))
    if update.excluded_keywords is not None:
        cleaned_kws = _normalize_keywords(update.excluded_keywords)
        prefs_store.set_pref(PREF_EXCLUDED_KEYWORDS, json.dumps(cleaned_kws))
    if update.week_starts_on is not None:
        if update.week_starts_on not in ALLOWED_WEEK_STARTS:
            raise HTTPException(
                status_code=400,
                detail=f"week_starts_on must be one of {sorted(ALLOWED_WEEK_STARTS)}",
            )
        prefs_store.set_pref(PREF_WEEK_STARTS_ON, update.week_starts_on)
    if update.excluded_calendar_categories is not None:
        cleaned_cats = _normalize_categories(update.excluded_calendar_categories)
        prefs_store.set_pref(PREF_EXCLUDED_CATEGORIES, json.dumps(cleaned_cats))
    if update.high_impact_keywords is not None:
        cleaned_hi = _normalize_high_impact_keywords(update.high_impact_keywords)
        prefs_store.set_pref(PREF_HIGH_IMPACT_KEYWORDS, json.dumps(cleaned_hi))
    if update.high_impact_calendar_categories is not None:
        cleaned_hi_cats = _normalize_high_impact_categories(update.high_impact_calendar_categories)
        prefs_store.set_pref(PREF_HIGH_IMPACT_CATEGORIES, json.dumps(cleaned_hi_cats))
    if update.umbrella_calendar_categories is not None:
        cleaned_umb = _normalize_umbrella_categories(update.umbrella_calendar_categories)
        prefs_store.set_pref(PREF_UMBRELLA_CATEGORIES, json.dumps(cleaned_umb))
    if update.preserve_calendar_categories is not None:
        cleaned_pres = _normalize_preserve_categories(update.preserve_calendar_categories)
        prefs_store.set_pref(PREF_PRESERVE_CATEGORIES, json.dumps(cleaned_pres))
    if update.exclude_private_meetings is not None:
        prefs_store.set_pref(
            PREF_EXCLUDE_PRIVATE, "true" if update.exclude_private_meetings else "false"
        )
    if update.organization_label is not None:
        cleaned_org = update.organization_label.strip()
        if len(cleaned_org) > MAX_ORGANIZATION_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"organization_label exceeds {MAX_ORGANIZATION_LENGTH} chars",
            )
        # Any explicit set (including clearing) marks the value as
        # user-confirmed so the orchestrator won't overwrite it on the
        # next scan's auto-derive pass.
        set_organization_label(cleaned_org, auto=False)
    return await get_prefs()
