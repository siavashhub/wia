"""Tests for the noise-reduction prefs added in hotfix/0.3.1.

Exercises the GET/PUT round-trip, validators, and the seeding behaviour
that gives Microsoft users a sensible default list of sister-company
internal domains.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from wia.api import prefs as prefs_api
from wia.app import create_app
from wia.storage import prefs as prefs_store
from wia.storage.db import init_db


@pytest.fixture()
def client():
    init_db()
    # Wipe the noise-reduction prefs so each test starts from defaults —
    # the WIA_DATA_DIR fixture in conftest.py is shared across the
    # session and another test may have set these values.
    for key in (
        prefs_api.PREF_ADDITIONAL_INTERNAL_DOMAINS,
        prefs_api.PREF_EXCLUDE_DECLINED,
        prefs_api.PREF_EXCLUDE_NO_RESPONSE,
        prefs_api.PREF_EXCLUDE_OPTIONAL_LARGE,
        prefs_api.PREF_OPTIONAL_LARGE_MIN_ATTENDEES,
        prefs_api.PREF_MIN_EMAIL_THREAD_HOURS,
        prefs_api.PREF_EXCLUDE_PASSIVE_TEAMS,
        prefs_api.PREF_ORGANIZATION,
        prefs_api.PREF_USER_UPN,
    ):
        prefs_store.delete_pref(key)
    return TestClient(create_app())


def test_defaults_when_unset(client: TestClient) -> None:
    body = client.get("/api/prefs").json()
    assert body["exclude_declined_meetings"] is True
    assert body["exclude_no_response_meetings"] is True
    assert body["exclude_optional_large_meetings"] is True
    assert body["optional_large_meeting_min_attendees"] == 20
    assert body["min_email_thread_hours"] == pytest.approx(0.1)
    assert body["exclude_passive_teams_threads"] is True


def test_round_trip_exclude_passive_teams_threads(client: TestClient) -> None:
    r = client.put("/api/prefs", json={"exclude_passive_teams_threads": False})
    assert r.status_code == 200
    assert r.json()["exclude_passive_teams_threads"] is False
    again = client.get("/api/prefs").json()
    assert again["exclude_passive_teams_threads"] is False


def test_round_trip_additional_internal_domains(client: TestClient) -> None:
    r = client.put(
        "/api/prefs",
        json={"additional_internal_domains": ["GitHub.com", "@xbox.com", "github.com"]},
    )
    assert r.status_code == 200
    body = r.json()
    # Lowercased, @-stripped, deduped.
    assert body["additional_internal_domains"] == ["github.com", "xbox.com"]

    again = client.get("/api/prefs").json()
    assert again["additional_internal_domains"] == ["github.com", "xbox.com"]


def test_invalid_domain_rejected(client: TestClient) -> None:
    r = client.put(
        "/api/prefs",
        json={"additional_internal_domains": ["not a valid domain!"]},
    )
    assert r.status_code == 400


def test_attendee_threshold_validator(client: TestClient) -> None:
    r = client.put("/api/prefs", json={"optional_large_meeting_min_attendees": 1})
    assert r.status_code == 400
    r = client.put("/api/prefs", json={"optional_large_meeting_min_attendees": 50})
    assert r.status_code == 200
    assert r.json()["optional_large_meeting_min_attendees"] == 50


def test_min_email_hours_validator(client: TestClient) -> None:
    r = client.put("/api/prefs", json={"min_email_thread_hours": -1})
    assert r.status_code == 400
    r = client.put("/api/prefs", json={"min_email_thread_hours": 0.25})
    assert r.status_code == 200
    assert r.json()["min_email_thread_hours"] == pytest.approx(0.25)


def test_microsoft_seed_present_for_microsoft_users(client: TestClient) -> None:
    prefs_store.set_pref(prefs_api.PREF_USER_UPN, "alice@microsoft.com")
    body = client.get("/api/prefs").json()
    # The pref hasn't been explicitly written, so the read-side seeds it.
    assert "github.com" in body["additional_internal_domains"]
    assert "linkedin.com" in body["additional_internal_domains"]


def test_explicit_empty_list_overrides_microsoft_seed(client: TestClient) -> None:
    prefs_store.set_pref(prefs_api.PREF_USER_UPN, "alice@microsoft.com")
    r = client.put("/api/prefs", json={"additional_internal_domains": []})
    assert r.status_code == 200
    assert r.json()["additional_internal_domains"] == []
    again = client.get("/api/prefs").json()
    assert again["additional_internal_domains"] == []


def test_non_microsoft_user_has_no_seed(client: TestClient) -> None:
    prefs_store.set_pref(prefs_api.PREF_USER_UPN, "alice@contoso.com")
    body = client.get("/api/prefs").json()
    assert body["additional_internal_domains"] == []


def test_boolean_toggles_round_trip(client: TestClient) -> None:
    r = client.put(
        "/api/prefs",
        json={
            "exclude_declined_meetings": False,
            "exclude_no_response_meetings": False,
            "exclude_optional_large_meetings": False,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exclude_declined_meetings"] is False
    assert body["exclude_no_response_meetings"] is False
    assert body["exclude_optional_large_meetings"] is False
