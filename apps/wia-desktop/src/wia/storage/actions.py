"""Action repository — CRUD + dedupe-aware upsert."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlmodel import select

from wia.core.actions.base import ActionCandidate
from wia.core.types import Action, ActionKind, ActionStatus, ActionUpdate
from wia.storage.db import get_session
from wia.storage.models import ActionRow


def _row_to_action(row: ActionRow) -> Action:
    try:
        payload = json.loads(row.payload) if row.payload else {}
        if not isinstance(payload, dict):
            payload = {}
    except json.JSONDecodeError:
        payload = {}
    try:
        kind = ActionKind(row.kind)
    except ValueError:
        # Forward-compat: ignore unknown kinds at the boundary so we don't
        # crash the API when a future build wrote a kind this version
        # doesn't know about.
        kind = ActionKind.FOLLOW_UP
    try:
        status = ActionStatus(row.status)
    except ValueError:
        status = ActionStatus.SUGGESTED
    return Action(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        week_of=row.week_of,
        kind=kind,
        title=row.title,
        rationale=row.rationale,
        source_entry_id=row.source_entry_id,
        dedupe_key=row.dedupe_key,
        payload=payload,
        status=status,
        priority=row.priority,
        snoozed_until=row.snoozed_until,
        completed_at=row.completed_at,
        dismissed_reason=row.dismissed_reason,
    )


def list_actions(
    *,
    week_of: str | None = None,
    statuses: list[ActionStatus] | None = None,
) -> list[Action]:
    """Return actions, newest-first within each priority bucket."""
    with get_session() as session:
        stmt = select(ActionRow)
        if week_of:
            stmt = stmt.where(ActionRow.week_of == week_of)
        if statuses:
            stmt = stmt.where(ActionRow.status.in_([s.value for s in statuses]))  # type: ignore[attr-defined]
        stmt = stmt.order_by(ActionRow.priority.desc(), ActionRow.created_at.desc())
        rows = session.exec(stmt).all()
        return [_row_to_action(r) for r in rows]


def get_action(action_id: int) -> Action | None:
    with get_session() as session:
        row = session.get(ActionRow, action_id)
        return _row_to_action(row) if row else None


def list_dismissed_dedupe_keys() -> frozenset[str]:
    """Return every dedupe key that's currently in the ``dismissed`` state.

    Suggesters consult this to suppress repeat suggestions a user has
    explicitly told WIA to stop showing.
    """
    with get_session() as session:
        rows = session.exec(
            select(ActionRow.dedupe_key).where(ActionRow.status == ActionStatus.DISMISSED.value)
        ).all()
        return frozenset(rows)


def upsert_candidates(week_of: str, candidates: list[ActionCandidate]) -> list[Action]:
    """Insert new candidates and refresh metadata on existing ones.

    Dedupe is by ``dedupe_key``. For existing rows we only refresh the
    cosmetic fields (title, rationale, priority, payload) — the user's
    status / snooze / completion stays untouched. Dismissed rows are
    *not* revived: a suggester that wants to re-emit a suppressed key
    must check ``ctx.dismissed_dedupe_keys`` itself.
    """
    if not candidates:
        return []
    now = datetime.now(UTC)
    upserted: list[Action] = []
    with get_session() as session:
        existing_rows = session.exec(
            select(ActionRow).where(
                ActionRow.dedupe_key.in_([c.dedupe_key for c in candidates])  # type: ignore[attr-defined]
            )
        ).all()
        by_key: dict[str, ActionRow] = {r.dedupe_key: r for r in existing_rows}
        for cand in candidates:
            row = by_key.get(cand.dedupe_key)
            if row is None:
                row = ActionRow(
                    created_at=now,
                    updated_at=now,
                    week_of=week_of,
                    kind=cand.kind.value,
                    title=cand.title,
                    rationale=cand.rationale,
                    source_entry_id=cand.source_entry_id,
                    dedupe_key=cand.dedupe_key,
                    payload=json.dumps(cand.payload or {}),
                    status=ActionStatus.SUGGESTED.value,
                    priority=cand.priority,
                )
                session.add(row)
            else:
                # Refresh cosmetic fields only — never overwrite user state.
                row.title = cand.title
                row.rationale = cand.rationale
                row.priority = cand.priority
                row.payload = json.dumps(cand.payload or {})
                row.updated_at = now
                session.add(row)
            session.commit()
            session.refresh(row)
            upserted.append(_row_to_action(row))
    return upserted


def update_action(action_id: int, update: ActionUpdate) -> Action | None:
    """Apply a status / snooze / dismiss-reason change."""
    with get_session() as session:
        row = session.get(ActionRow, action_id)
        if row is None:
            return None
        data = update.model_dump(exclude_unset=True)
        if "status" in data and data["status"] is not None:
            new_status = data["status"]
            row.status = new_status.value if hasattr(new_status, "value") else str(new_status)
            if row.status == ActionStatus.COMPLETED.value:
                row.completed_at = datetime.now(UTC)
        if "snoozed_until" in data:
            row.snoozed_until = data["snoozed_until"]
            if row.snoozed_until is not None and "status" not in data:
                # Snoozing implicitly transitions to the snoozed state so the
                # list view can hide the row until the timer elapses.
                row.status = ActionStatus.SNOOZED.value
        if "dismissed_reason" in data:
            row.dismissed_reason = data["dismissed_reason"]
        row.updated_at = datetime.now(UTC)
        session.add(row)
        session.commit()
        session.refresh(row)
        return _row_to_action(row)
