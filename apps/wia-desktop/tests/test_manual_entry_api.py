"""Tests for the manual-entry and notes paths of the entries API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select
from wia.app import create_app
from wia.storage.db import get_session, init_db
from wia.storage.models import TimeEntryRow


@pytest.fixture()
def client() -> TestClient:
    init_db()
    # Clear time_entry between tests so assertions are deterministic.
    with get_session() as s:
        for row in s.exec(select(TimeEntryRow)).all():
            s.delete(row)
        s.commit()
    return TestClient(create_app())


def test_post_manual_entry_with_daily_hours_derives_duration_and_week(
    client: TestClient,
) -> None:
    r = client.post(
        "/api/entries",
        json={
            "label": "Customer call",
            "category": "Customer",
            "daily_hours": {"2026-04-08": 2.0, "2026-04-09": 1.5},
            "impact": "high",
            "notes": "Reviewed proposal.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "Customer call"
    assert body["category"] == "Customer"
    assert body["duration_hours"] == pytest.approx(3.5)
    # Monday of Apr 8 2026 (Wed) is Apr 6.
    assert body["week_of"] == "2026-04-06"
    assert body["manual"] is True
    assert body["notes"] == "Reviewed proposal."
    assert body["impact"] == "high"


def test_post_manual_entry_with_duration_only_uses_current_week(
    client: TestClient,
) -> None:
    r = client.post(
        "/api/entries",
        json={
            "label": "Offsite prep",
            "duration_hours": 2.0,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duration_hours"] == pytest.approx(2.0)
    assert body["week_of"]  # something was derived
    assert body["manual"] is True


def test_post_manual_entry_rejects_missing_duration(client: TestClient) -> None:
    r = client.post("/api/entries", json={"label": "Nothing"})
    assert r.status_code == 400


def test_post_manual_entry_rejects_zero_duration(client: TestClient) -> None:
    r = client.post(
        "/api/entries",
        json={"label": "Zero", "duration_hours": 0},
    )
    assert r.status_code == 400


def test_post_manual_entry_rejects_empty_label(client: TestClient) -> None:
    r = client.post(
        "/api/entries",
        json={"label": "", "duration_hours": 1.0},
    )
    assert r.status_code == 422  # pydantic min_length=1


def test_patch_entry_notes(client: TestClient) -> None:
    # Seed an entry via the manual API for convenience.
    created = client.post(
        "/api/entries",
        json={"label": "Item", "duration_hours": 1.0},
    ).json()
    eid = created["id"]
    r = client.patch(f"/api/entries/{eid}", json={"notes": "Follow-up next week."})
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "Follow-up next week."


def test_patch_entry_daily_hours_recomputes_duration(client: TestClient) -> None:
    created = client.post(
        "/api/entries",
        json={"label": "Item", "duration_hours": 1.0, "week_of": "2026-04-06"},
    ).json()
    eid = created["id"]
    r = client.patch(
        f"/api/entries/{eid}",
        json={"daily_hours": {"2026-04-06": 2.0, "2026-04-07": 1.0}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["daily_hours"] == {"2026-04-06": 2.0, "2026-04-07": 1.0}
    assert body["duration_hours"] == pytest.approx(3.0)


def test_manual_entry_tagged_with_manual_source(client: TestClient) -> None:
    body = client.post(
        "/api/entries",
        json={"label": "Phone call", "duration_hours": 0.5},
    ).json()
    assert body["sources"] == ["manual"]
