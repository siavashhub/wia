"""Suggester contract for WIA Actions.

Suggesters are pure functions: they receive a :class:`SuggesterContext`
(read-only views of entries, dismissed dedupe keys, and the current
week) and return zero or more :class:`ActionCandidate` rows. They never
touch the DB, HTTP, or MCP layers — that's the orchestrator's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from wia.core.types import ActionKind, TimeEntry


@dataclass(frozen=True)
class SuggesterContext:
    """Inputs shared by every suggester during a single scan."""

    week_of: str
    """ISO Monday of the week the orchestrator just finished scanning."""

    entries: list[TimeEntry]
    """All persisted entries for ``week_of`` (post-merge)."""

    dismissed_dedupe_keys: frozenset[str] = frozenset()
    """Dedupe keys the user has previously dismissed — suggesters must
    not re-emit candidates for these keys. The orchestrator populates
    this from the actions repo."""


@dataclass
class ActionCandidate:
    """A suggester's output row, pre-persistence."""

    kind: ActionKind
    title: str
    rationale: str
    dedupe_key: str
    source_entry_id: int | None = None
    payload: dict = field(default_factory=dict)
    priority: int = 50


class Suggester(Protocol):
    """Pluggable suggester interface."""

    kind: ActionKind

    def suggest(self, ctx: SuggesterContext) -> list[ActionCandidate]: ...
