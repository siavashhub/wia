"""Decision-note suggester — flags meetings that produced (or should produce) a decision.

Different intent from :mod:`wia.core.actions.follow_up`:

* **follow_up** says "send a recap email to the attendees".
* **decision_note** says "capture *what was decided* in a durable doc"
  (Loop / OneNote / repo README — wherever the user keeps decisions).

These are split so the same entry doesn't surface two near-identical
cards.

Triggers:

1. **Notes mention a decision**: phrases like "we decided", "agreed to",
   "the decision is", "approved", "go/no-go". Strong signal — the user
   has already written down a fragment of the decision and just needs
   to formalize it. Priority 75.
2. **Meeting label** matches a decision-style meeting kind (decision,
   review, approval, sign-off, go/no-go). Weaker signal. Priority 55.
"""

from __future__ import annotations

import re

from wia.core.actions.base import ActionCandidate, SuggesterContext
from wia.core.types import ActionKind, Confidence

_NOTE_RE = re.compile(
    r"\b("
    r"we (?:decided|agreed|approved|chose)"
    r"|decision (?:was|is)"
    r"|the decision"
    r"|agreed to"
    r"|approved"
    r"|go[/ ]no[- ]?go"
    r"|sign[- ]?off"
    r")\b",
    re.IGNORECASE,
)

_LABEL_RE = re.compile(
    r"\b(decision|review|approval|sign[- ]?off|go[/ ]no[- ]?go)\b",
    re.IGNORECASE,
)


class DecisionNoteSuggester:
    """Suggests "capture the decision" actions for decision-style meetings."""

    kind = ActionKind.DECISION_NOTE

    def suggest(self, ctx: SuggesterContext) -> list[ActionCandidate]:
        out: list[ActionCandidate] = []
        for e in ctx.entries:
            if e.manual or e.id is None:
                continue
            if e.confidence is not Confidence.HIGH:
                continue
            note_match = _NOTE_RE.search(e.notes or "")
            label_match = _LABEL_RE.search(e.label or "")
            if not (note_match or label_match):
                continue

            dedupe = f"decision_note:{ctx.week_of}:{e.id}"
            if dedupe in ctx.dismissed_dedupe_keys:
                continue

            if note_match:
                phrase = note_match.group(0).strip()
                rationale = f'Your notes on "{e.label}" mention "{phrase}".'
                priority = 75
            else:
                kind_word = label_match.group(0).strip().lower()
                rationale = (
                    f'"{e.label}" looks like a {kind_word} meeting — '
                    "capture the decision so it's findable later."
                )
                priority = 55

            out.append(
                ActionCandidate(
                    kind=ActionKind.DECISION_NOTE,
                    title=f'Document the decision from "{e.label}"',
                    rationale=rationale,
                    dedupe_key=dedupe,
                    source_entry_id=e.id,
                    payload={
                        "entry_label": e.label,
                        "entry_category": e.category or "",
                        "entry_notes": e.notes or "",
                    },
                    priority=priority,
                )
            )
        return out
