"""Decision-note (Markdown) draft generator."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from wia.core.types import Action


@dataclass(frozen=True)
class NoteDraft:
    """A drafted Markdown decision note."""

    filename: str
    body: str


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug or "decision"


def build_decision_note(action: Action) -> NoteDraft:
    """Return a Markdown decision note for a ``decision_note`` action.

    The template intentionally has structured headings (Context /
    Decision / Alternatives / Next steps) so the artifact stays useful
    weeks later when the user is trying to find *why* something was
    decided.
    """
    label = (action.payload.get("entry_label") or "Decision").strip() or "Decision"
    notes = (action.payload.get("entry_notes") or "").strip()
    today = date.today().isoformat()
    filename = f"decision-{today}-{_slugify(label)}.md"

    notes_block = notes if notes else "_<paste any raw notes from the meeting here>_"
    body = f"""# {label}

**Date:** {today}
**Week of:** {action.week_of}

## Context
<why this decision was needed>

## Decision
<what was decided, in one or two sentences>

## Alternatives considered
- <option A — why not>
- <option B — why not>

## Next steps
- <owner> — <action> — <when>

## Raw notes
{notes_block}
"""
    return NoteDraft(filename=filename, body=body)
