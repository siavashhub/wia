"""Registry of WIA Actions suggesters.

Centralises the list of active suggesters so the orchestrator can run
them all with a single call. Suggesters are pure — any exception from
one is logged and skipped, never propagated to the briefing pipeline.
"""

from __future__ import annotations

import logging

from wia.core.actions.base import ActionCandidate, Suggester, SuggesterContext
from wia.core.actions.decision_note import DecisionNoteSuggester
from wia.core.actions.follow_up import FollowUpSuggester

log = logging.getLogger(__name__)

_SUGGESTERS: list[Suggester] = [FollowUpSuggester(), DecisionNoteSuggester()]


def run_all(ctx: SuggesterContext) -> list[ActionCandidate]:
    """Run every registered suggester and return their combined output."""
    out: list[ActionCandidate] = []
    for suggester in _SUGGESTERS:
        try:
            out.extend(suggester.suggest(ctx))
        except Exception:
            log.exception("Suggester %s failed", suggester.kind)
    return out
