"""Tests for the decision_note suggester and the draft endpoint."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select
from wia.app import create_app
from wia.core.actions import SuggesterContext, run_all
from wia.core.actions.decision_note import DecisionNoteSuggester
from wia.core.actions.drafts import build_decision_note, build_follow_up_email
from wia.core.actions.follow_up import FollowUpSuggester
from wia.core.types import Action, ActionKind, ActionStatus, Confidence, Impact, TimeEntry
from wia.storage import actions as actions_repo
from wia.storage.db import get_session, init_db
from wia.storage.models import ActionRow, TimeEntryRow


@pytest.fixture()
def db_clean() -> None:
    init_db()
    with get_session() as s:
        for row in s.exec(select(ActionRow)).all():
            s.delete(row)
        for row in s.exec(select(TimeEntryRow)).all():
            s.delete(row)
        s.commit()


def _entry(*, label: str, notes: str = "") -> TimeEntry:
    row = TimeEntryRow(
        label=label,
        category="Customer",
        duration_hours=1.0,
        confidence=Confidence.HIGH.value,
        impact=Impact.LOW.value,
        week_of="2026-05-18",
        source_block_ids="",
        notes=notes,
        manual=False,
        sources="calendar",
        user_edited=False,
    )
    with get_session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
    return TimeEntry(
        id=row.id,
        label=row.label,
        category=row.category,
        duration_hours=row.duration_hours,
        confidence=Confidence.HIGH,
        impact=Impact.LOW,
        week_of=row.week_of,
        source_block_ids=[],
        notes=row.notes,
        manual=False,
        sources=["calendar"],
    )


# ---- decision_note suggester ---------------------------------------------


def test_decision_note_fires_on_notes_phrase(db_clean: None) -> None:
    e = _entry(label="Pricing review", notes="We decided to launch in Q3.")
    out = DecisionNoteSuggester().suggest(SuggesterContext(week_of="2026-05-18", entries=[e]))
    assert len(out) == 1
    assert out[0].kind is ActionKind.DECISION_NOTE
    assert out[0].priority == 75


def test_decision_note_fires_on_label(db_clean: None) -> None:
    e = _entry(label="Architecture review")
    out = DecisionNoteSuggester().suggest(SuggesterContext(week_of="2026-05-18", entries=[e]))
    assert len(out) == 1
    assert out[0].priority == 55


def test_decision_note_and_follow_up_do_not_overlap(db_clean: None) -> None:
    # ``review`` is owned by decision_note now; follow_up shouldn't double-fire.
    e = _entry(label="Architecture review")
    candidates = run_all(SuggesterContext(week_of="2026-05-18", entries=[e]))
    kinds = sorted(c.kind.value for c in candidates)
    assert kinds == ["decision_note"]


def test_follow_up_still_fires_on_its_own_label(db_clean: None) -> None:
    e = _entry(label="Project kickoff")
    candidates = run_all(SuggesterContext(week_of="2026-05-18", entries=[e]))
    kinds = sorted(c.kind.value for c in candidates)
    assert kinds == ["follow_up"]


# ---- Draft generators -----------------------------------------------------


def _make_action(kind: ActionKind, *, label: str, notes: str = "") -> Action:
    now = datetime(2026, 5, 18, 9, 0, 0)
    return Action(
        id=1,
        created_at=now,
        updated_at=now,
        week_of="2026-05-18",
        kind=kind,
        title="x",
        rationale="y",
        dedupe_key=f"{kind.value}:x",
        payload={"entry_label": label, "entry_notes": notes},
        status=ActionStatus.SUGGESTED,
    )


def test_build_follow_up_email_has_label_in_subject_and_body() -> None:
    action = _make_action(ActionKind.FOLLOW_UP, label="Contoso QBR")
    draft = build_follow_up_email(action)
    assert "Contoso QBR" in draft.subject
    assert "Contoso QBR" in draft.body
    assert draft.mailto.startswith("mailto:?subject=")
    assert "Contoso%20QBR" in draft.mailto
    # Body round-trips through mailto's URL encoding.
    assert "Next steps" in unquote(draft.mailto)


def test_build_decision_note_includes_notes_and_label() -> None:
    action = _make_action(
        ActionKind.DECISION_NOTE,
        label="Pricing review",
        notes="We decided to launch in Q3.",
    )
    note = build_decision_note(action)
    assert note.filename.endswith(".md")
    assert "pricing-review" in note.filename
    assert "# Pricing review" in note.body
    assert "We decided to launch in Q3." in note.body


def test_build_decision_note_handles_empty_notes() -> None:
    action = _make_action(ActionKind.DECISION_NOTE, label="Sign-off")
    note = build_decision_note(action)
    assert "paste any raw notes" in note.body


# ---- /draft endpoint ------------------------------------------------------


@pytest.fixture()
def client(db_clean: None) -> TestClient:
    return TestClient(create_app())


def _seed(kind_label: str) -> int:
    # Use a label that triggers the suggester for the requested kind.
    if kind_label == "follow_up":
        e = _entry(label="Project kickoff")
        cands = FollowUpSuggester().suggest(SuggesterContext(week_of="2026-05-18", entries=[e]))
    else:
        e = _entry(label="Architecture review")
        cands = DecisionNoteSuggester().suggest(SuggesterContext(week_of="2026-05-18", entries=[e]))
    [created] = actions_repo.upsert_candidates("2026-05-18", cands)
    assert created.id is not None
    return created.id


def test_draft_endpoint_returns_email_for_follow_up(client: TestClient) -> None:
    aid = _seed("follow_up")
    r = client.post(f"/api/actions/{aid}/draft")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "email"
    assert "subject" in body and "body" in body
    assert body["mailto"].startswith("mailto:?")


def test_draft_endpoint_returns_markdown_for_decision_note(client: TestClient) -> None:
    aid = _seed("decision_note")
    r = client.post(f"/api/actions/{aid}/draft")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "markdown"
    assert body["filename"].endswith(".md")
    assert body["body"].startswith("# ")


def test_draft_endpoint_does_not_change_status(client: TestClient) -> None:
    aid = _seed("follow_up")
    before = client.get(f"/api/actions/{aid}").json()
    client.post(f"/api/actions/{aid}/draft")
    after = client.get(f"/api/actions/{aid}").json()
    assert before["status"] == after["status"] == "suggested"


def test_draft_endpoint_404_for_unknown(client: TestClient) -> None:
    assert client.post("/api/actions/9999/draft").status_code == 404
