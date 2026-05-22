"""Tests for the follow_up suggester and the actions API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select
from wia.app import create_app
from wia.core.actions import SuggesterContext, run_all
from wia.core.actions.follow_up import FollowUpSuggester
from wia.core.types import ActionKind, ActionStatus, Confidence, Impact, TimeEntry
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


def _entry(
    *,
    label: str,
    notes: str = "",
    confidence: Confidence = Confidence.HIGH,
    manual: bool = False,
) -> TimeEntry:
    """Insert a non-manual time entry directly via the session.

    ``entries_repo.create_entry`` forces ``manual=True``, which the
    follow_up suggester intentionally ignores. Tests need the
    scan-pipeline shape, so write the row ourselves.
    """
    row = TimeEntryRow(
        label=label,
        category="Customer",
        duration_hours=1.0,
        confidence=confidence.value,
        impact=Impact.LOW.value,
        week_of="2026-05-18",
        source_block_ids="",
        notes=notes,
        manual=manual,
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
        confidence=confidence,
        impact=Impact.LOW,
        week_of=row.week_of,
        source_block_ids=[],
        notes=row.notes,
        manual=row.manual,
        sources=["calendar"],
    )


# ---- Suggester ------------------------------------------------------------


def test_follow_up_fires_on_notes_commitment(db_clean: None) -> None:
    e = _entry(label="Contoso sync", notes="I'll send notes.")
    ctx = SuggesterContext(week_of="2026-05-18", entries=[e])
    out = FollowUpSuggester().suggest(ctx)
    assert len(out) == 1
    assert out[0].kind is ActionKind.FOLLOW_UP
    assert "I'll send" in out[0].rationale.lower() or "i'll send" in out[0].rationale.lower()
    assert out[0].priority == 70
    assert out[0].dedupe_key == f"follow_up:2026-05-18:{e.id}"


def test_follow_up_fires_on_meeting_kind_label(db_clean: None) -> None:
    e = _entry(label="Project kickoff")
    out = FollowUpSuggester().suggest(SuggesterContext(week_of="2026-05-18", entries=[e]))
    assert len(out) == 1
    assert out[0].priority == 50
    assert "kickoff" in out[0].rationale.lower() or "kick" in out[0].rationale.lower()


def test_follow_up_skips_unrelated_entries(db_clean: None) -> None:
    e = _entry(label="Coffee chat")
    assert FollowUpSuggester().suggest(SuggesterContext(week_of="2026-05-18", entries=[e])) == []


def test_follow_up_skips_manual_entries(db_clean: None) -> None:
    # Manual entries are user-authored — WIA shouldn't infer follow-ups from them.
    e = _entry(label="Project kickoff", manual=True)
    assert FollowUpSuggester().suggest(SuggesterContext(week_of="2026-05-18", entries=[e])) == []


def test_follow_up_skips_non_meeting_confidence(db_clean: None) -> None:
    # MEDIUM confidence = Teams/email aggregates; suggester targets meetings only.
    e = _entry(label="Project kickoff", confidence=Confidence.MEDIUM)
    assert FollowUpSuggester().suggest(SuggesterContext(week_of="2026-05-18", entries=[e])) == []


def test_follow_up_respects_dismissed_dedupe_keys(db_clean: None) -> None:
    e = _entry(label="Project kickoff")
    dismissed = frozenset({f"follow_up:2026-05-18:{e.id}"})
    ctx = SuggesterContext(week_of="2026-05-18", entries=[e], dismissed_dedupe_keys=dismissed)
    assert FollowUpSuggester().suggest(ctx) == []


def test_registry_runs_all_suggesters(db_clean: None) -> None:
    e = _entry(label="Project kickoff")
    out = run_all(SuggesterContext(week_of="2026-05-18", entries=[e]))
    assert any(c.kind is ActionKind.FOLLOW_UP for c in out)


# ---- Storage upsert -------------------------------------------------------


def test_upsert_is_idempotent_by_dedupe_key(db_clean: None) -> None:
    e = _entry(label="Project kickoff")
    cands = FollowUpSuggester().suggest(SuggesterContext(week_of="2026-05-18", entries=[e]))
    first = actions_repo.upsert_candidates("2026-05-18", cands)
    second = actions_repo.upsert_candidates("2026-05-18", cands)
    assert len(first) == len(second) == 1
    assert first[0].id == second[0].id  # same row, refreshed in place


def test_upsert_preserves_user_status(db_clean: None) -> None:
    e = _entry(label="Project kickoff")
    cands = FollowUpSuggester().suggest(SuggesterContext(week_of="2026-05-18", entries=[e]))
    [created] = actions_repo.upsert_candidates("2026-05-18", cands)
    actions_repo.update_action(
        created.id,  # type: ignore[arg-type]
        update=__import__("wia.core.types", fromlist=["ActionUpdate"]).ActionUpdate(
            status=ActionStatus.ACCEPTED
        ),
    )
    # Re-run: cosmetic refresh must not revert the accepted status.
    actions_repo.upsert_candidates("2026-05-18", cands)
    refreshed = actions_repo.get_action(created.id)  # type: ignore[arg-type]
    assert refreshed is not None
    assert refreshed.status is ActionStatus.ACCEPTED


# ---- API ------------------------------------------------------------------


@pytest.fixture()
def client(db_clean: None) -> TestClient:
    return TestClient(create_app())


def _seed_action(label: str = "Project kickoff", notes: str = "") -> int:
    e = _entry(label=label, notes=notes)
    cands = FollowUpSuggester().suggest(SuggesterContext(week_of="2026-05-18", entries=[e]))
    [created] = actions_repo.upsert_candidates("2026-05-18", cands)
    assert created.id is not None
    return created.id


def test_list_actions_filters_resolved_by_default(client: TestClient) -> None:
    aid = _seed_action()
    # Dismiss it — should disappear from the default list.
    client.post(f"/api/actions/{aid}/dismiss", json={"reason": "not relevant"})
    r = client.get("/api/actions")
    assert r.status_code == 200
    assert all(a["status"] != "dismissed" for a in r.json())
    r_all = client.get("/api/actions?include_resolved=true")
    assert any(a["id"] == aid for a in r_all.json())


def test_accept_complete_snooze_dismiss(client: TestClient) -> None:
    aid = _seed_action()
    assert client.post(f"/api/actions/{aid}/accept").json()["status"] == "accepted"
    assert client.post(f"/api/actions/{aid}/complete").json()["status"] == "completed"
    body = client.post(
        f"/api/actions/{aid}/snooze", json={"snoozed_until": "2026-06-01T09:00:00+00:00"}
    ).json()
    assert body["status"] == "snoozed"
    assert body["snoozed_until"].startswith("2026-06-01")
    body = client.post(f"/api/actions/{aid}/dismiss", json={"reason": "wrong"}).json()
    assert body["status"] == "dismissed"
    assert body["dismissed_reason"] == "wrong"


def test_action_endpoints_404_for_unknown(client: TestClient) -> None:
    assert client.get("/api/actions/9999").status_code == 404
    assert client.post("/api/actions/9999/accept").status_code == 404
