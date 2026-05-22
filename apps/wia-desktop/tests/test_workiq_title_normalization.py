"""Tests for source-aware title normalisation in ``_event_to_block``.

Work IQ rewrites recurring Teams chat titles with a per-day parenthetical
summary, and stamps date/option suffixes onto recurring calendar workshop
events. Both patterns prevent the aggregator from merging conceptually-
identical activity into a single :class:`TimeEntry` row. The normalisation
helpers collapse them while preserving the original via
``metadata['original_title']``.
"""

from __future__ import annotations

from wia.core.types import Source
from wia.mcp_clients.workiq import (
    _event_to_block,
    _normalize_calendar_title,
    _normalize_chat_title,
)


def _ev(title: str) -> dict:
    return {
        "title": title,
        "start": "2026-05-19T09:00:00+00:00",
        "end": "2026-05-19T09:30:00+00:00",
        "participants": [],
    }


# --- chat-style normalisation --------------------------------------------------


def test_chat_strips_trailing_paren_summary():
    assert _normalize_chat_title("O.U.C.H. group chat (Clawpilot discussion)") == (
        "O.U.C.H. group chat"
    )


def test_chat_leaves_inner_parens_alone():
    # Only the trailing parenthetical is stripped; nested topic markers
    # stay so two genuinely-different conversations don't collapse.
    assert _normalize_chat_title("Chat with Abe (re: GHCP) about training") == (
        "Chat with Abe (re: GHCP) about training"
    )


def test_chat_noop_without_paren():
    assert _normalize_chat_title("O.U.C.H. group chat") == "O.U.C.H. group chat"


def test_chat_empty_title_passthrough():
    assert _normalize_chat_title("") == ""


# --- calendar-style normalisation ----------------------------------------------


def test_calendar_strips_pipe_date_suffix():
    assert (
        _normalize_calendar_title(
            "FY26 Agent 365 LevelUp Series Workshop VBD| 18 May 8am - Wkshop 3"
        )
        == "FY26 Agent 365 LevelUp Series Workshop VBD"
    )


def test_calendar_strips_multiple_pipe_segments_iteratively():
    assert (
        _normalize_calendar_title("OneLake Security | 19 MAY 2026 | 8am - 9am | - option 1")
        == "OneLake Security"
    )


def test_calendar_strips_option_suffix():
    assert _normalize_calendar_title("Fabric Ontologies Workshop - option 2") == (
        "Fabric Ontologies Workshop"
    )


def test_calendar_preserves_legitimate_pipe_segments():
    # Pipe segments without a digit are kept — these tend to be real
    # title fragments (team / track names) rather than date stamps.
    assert _normalize_calendar_title("Project A | Team B") == "Project A | Team B"


def test_calendar_noop_for_clean_title():
    assert _normalize_calendar_title("Weekly Team Sync") == "Weekly Team Sync"


# --- _event_to_block integration ----------------------------------------------


def test_event_to_block_normalises_teams_title_and_preserves_original():
    b = _event_to_block(_ev("O.U.C.H. group chat (Clawpilot discussion)"), source=Source.TEAMS)
    assert b.title == "O.U.C.H. group chat"
    assert b.metadata["original_title"] == "O.U.C.H. group chat (Clawpilot discussion)"


def test_event_to_block_normalises_email_title():
    b = _event_to_block(_ev("Project alpha thread (Mon recap)"), source=Source.EMAIL)
    assert b.title == "Project alpha thread"
    assert b.metadata["original_title"] == "Project alpha thread (Mon recap)"


def test_event_to_block_normalises_calendar_title():
    b = _event_to_block(
        _ev("FY26 Agent 365 LevelUp Series Workshop VBD| 18 May 8am - Wkshop 3"),
        source=Source.CALENDAR,
    )
    assert b.title == "FY26 Agent 365 LevelUp Series Workshop VBD"
    assert (
        b.metadata["original_title"]
        == "FY26 Agent 365 LevelUp Series Workshop VBD| 18 May 8am - Wkshop 3"
    )


def test_event_to_block_no_original_title_when_unchanged():
    b = _event_to_block(_ev("Plain meeting title"), source=Source.CALENDAR)
    assert b.title == "Plain meeting title"
    assert "original_title" not in b.metadata


# --- participation metadata capture -------------------------------------------


def test_event_to_block_captures_participation_fields():
    ev = _ev("group chat")
    ev["iParticipated"] = False
    ev["messagesFromMe"] = 0
    ev["messagesTotal"] = 14
    b = _event_to_block(ev, source=Source.TEAMS)
    assert b.metadata["i_participated"] == "false"
    assert b.metadata["messages_from_me"] == "0"
    assert b.metadata["messages_total"] == "14"


def test_event_to_block_accepts_snake_case_participation_fields():
    ev = _ev("group chat")
    ev["i_participated"] = True
    ev["messages_from_me"] = 3
    b = _event_to_block(ev, source=Source.TEAMS)
    assert b.metadata["i_participated"] == "true"
    assert b.metadata["messages_from_me"] == "3"


def test_event_to_block_omits_participation_when_absent():
    b = _event_to_block(_ev("group chat"), source=Source.TEAMS)
    assert "i_participated" not in b.metadata
    assert "messages_from_me" not in b.metadata
    assert "messages_total" not in b.metadata
