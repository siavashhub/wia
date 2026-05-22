"""Follow-up suggester — flags meetings that likely need a follow-up.

Heuristic (v0.4 — no LLM, no email correlation yet):

1. **Notes commitment**: the user wrote a phrase like "I'll send notes",
   "send recap", "next steps", or "follow up with …" in the entry's
   notes. Strong signal — the user has explicitly said they owe
   somebody something. Priority 70.
2. **Meeting kind**: the entry's label matches a high-follow-up
   meeting kind (kickoff, debrief, planning, decision, review).
   Weaker signal, gated on having ≥2 attendees so 1:1s and personal
   blocks don't fire. Priority 50.

Only meetings (entries with HIGH confidence — see
:func:`wia.core.orchestrator._totals_from_entries`) are considered.
Manual entries are skipped — WIA didn't see the underlying activity
and shouldn't pretend it has an opinion about a follow-up.
"""

from __future__ import annotations

import re

from wia.core.actions.base import ActionCandidate, SuggesterContext
from wia.core.types import ActionKind, Confidence

# Phrases that strongly imply the user owes somebody an artifact.
# Kept conservative — false positives here are annoying because the
# UI will surface them as actionable cards with the user's own words.
_NOTE_RE = re.compile(
    r"\b("
    r"i['\u2019]ll send"
    r"|i will send"
    r"|i['\u2019]ll follow[- ]?up"
    r"|i will follow[- ]?up"
    r"|send (?:the |a )?(?:notes|recap|summary|minutes|follow[- ]?up)"
    r"|follow[- ]?up with"
    r"|next steps?"
    r"|action items?"
    r")\b",
    re.IGNORECASE,
)

# Meeting kinds that almost always produce takeaways worth circulating.
# NOTE: ``decision`` / ``review`` are intentionally omitted here — the
# decision_note suggester owns those triggers so the user gets one card,
# not two, for the same entry.
_LABEL_RE = re.compile(
    r"\b(kick[- ]?off|debrief|wrap[- ]?up|retro(?:spective)?|planning|qbr)\b",
    re.IGNORECASE,
)


class FollowUpSuggester:
    """Suggests "send a follow-up" actions for meeting entries."""

    kind = ActionKind.FOLLOW_UP

    def suggest(self, ctx: SuggesterContext) -> list[ActionCandidate]:
        out: list[ActionCandidate] = []
        for e in ctx.entries:
            if e.manual or e.id is None:
                continue
            if e.confidence is not Confidence.HIGH:
                continue  # meetings only — Teams/email entries aren't follow-up triggers
            note_match = _NOTE_RE.search(e.notes or "")
            label_match = _LABEL_RE.search(e.label or "")
            if not (note_match or label_match):
                continue

            dedupe = f"follow_up:{ctx.week_of}:{e.id}"
            if dedupe in ctx.dismissed_dedupe_keys:
                continue

            if note_match:
                phrase = note_match.group(0).strip()
                rationale = f'Your notes on "{e.label}" mention "{phrase}".'
                priority = 70
            else:
                kind_word = label_match.group(0).strip().lower()
                rationale = (
                    f'"{e.label}" looks like a {kind_word} — '
                    "these usually warrant a follow-up to attendees."
                )
                priority = 50

            out.append(
                ActionCandidate(
                    kind=ActionKind.FOLLOW_UP,
                    title=f'Send follow-up for "{e.label}"',
                    rationale=rationale,
                    dedupe_key=dedupe,
                    source_entry_id=e.id,
                    payload={
                        "entry_label": e.label,
                        "entry_category": e.category or "",
                    },
                    priority=priority,
                )
            )
        return out
