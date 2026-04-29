"""Key-value preferences store backed by ``UserPref``."""

from __future__ import annotations

from sqlmodel import select

from wia.storage.db import get_session
from wia.storage.models import UserPref


def get_pref(key: str) -> str | None:
    with get_session() as session:
        row = session.get(UserPref, key)
        return row.value if row else None


def set_pref(key: str, value: str) -> None:
    with get_session() as session:
        row = session.get(UserPref, key)
        if row is None:
            session.add(UserPref(key=key, value=value))
        else:
            row.value = value
            session.add(row)
        session.commit()


def all_prefs() -> dict[str, str]:
    with get_session() as session:
        return {r.key: r.value for r in session.exec(select(UserPref)).all()}
