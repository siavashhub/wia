"""User preferences endpoints (theme, signal selection, etc.)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from wia.storage import prefs as prefs_store

router = APIRouter()

ALLOWED_THEMES = {"light", "dark", "system"}
ALLOWED_SIGNALS = ("calendar", "teams", "email")
DEFAULT_SIGNALS = ["calendar"]
PREF_THEME = "theme"
PREF_SIGNALS = "enabled_signals"


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


def get_enabled_signals() -> list[str]:
    """Public helper used by the orchestrator to know which signals to pull."""
    return _read_signals()


class Prefs(BaseModel):
    theme: str = "system"
    enabled_signals: list[str] = Field(default_factory=lambda: list(DEFAULT_SIGNALS))


class PrefsUpdate(BaseModel):
    theme: str | None = None
    enabled_signals: list[str] | None = None


@router.get("")
async def get_prefs() -> Prefs:
    return Prefs(
        theme=prefs_store.get_pref(PREF_THEME) or "system",
        enabled_signals=_read_signals(),
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
    return await get_prefs()
