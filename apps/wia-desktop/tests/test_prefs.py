"""Tests for the user preferences API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from wia.app import create_app
from wia.storage.db import init_db


@pytest.fixture()
def client():
    init_db()
    return TestClient(create_app())


def test_default_week_starts_on_is_sunday(client: TestClient) -> None:
    r = client.get("/api/prefs")
    assert r.status_code == 200
    assert r.json()["week_starts_on"] == "sun"


def test_set_week_starts_on_monday_roundtrips(client: TestClient) -> None:
    r = client.put("/api/prefs", json={"week_starts_on": "mon"})
    assert r.status_code == 200
    assert r.json()["week_starts_on"] == "mon"

    again = client.get("/api/prefs")
    assert again.json()["week_starts_on"] == "mon"


def test_invalid_week_starts_on_rejected(client: TestClient) -> None:
    r = client.put("/api/prefs", json={"week_starts_on": "wed"})
    assert r.status_code == 400
