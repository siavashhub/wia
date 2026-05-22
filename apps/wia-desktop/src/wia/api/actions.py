"""WIA Actions HTTP endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from wia.core.actions.drafts import build_decision_note, build_follow_up_email
from wia.core.types import Action, ActionKind, ActionStatus, ActionUpdate
from wia.storage import actions as repo

router = APIRouter()


class SnoozePayload(BaseModel):
    snoozed_until: datetime


class DismissPayload(BaseModel):
    reason: str | None = None


@router.get("")
async def list_actions(
    week_of: str | None = None,
    include_resolved: bool = False,
) -> list[Action]:
    """List actions for a week.

    By default we hide the terminal states (``dismissed`` /
    ``completed``) so the UI's primary list stays focused on open work.
    Pass ``include_resolved=true`` to retrieve the full history.
    """
    statuses: list[ActionStatus] | None = None
    if not include_resolved:
        statuses = [
            ActionStatus.SUGGESTED,
            ActionStatus.ACCEPTED,
            ActionStatus.SNOOZED,
        ]
    return repo.list_actions(week_of=week_of, statuses=statuses)


@router.get("/{action_id}")
async def get_action(action_id: int) -> Action:
    action = repo.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="action not found")
    return action


@router.post("/{action_id}/accept")
async def accept_action(action_id: int) -> Action:
    return _update_or_404(action_id, ActionUpdate(status=ActionStatus.ACCEPTED))


@router.post("/{action_id}/complete")
async def complete_action(action_id: int) -> Action:
    return _update_or_404(action_id, ActionUpdate(status=ActionStatus.COMPLETED))


@router.post("/{action_id}/snooze")
async def snooze_action(action_id: int, payload: SnoozePayload) -> Action:
    return _update_or_404(
        action_id,
        ActionUpdate(status=ActionStatus.SNOOZED, snoozed_until=payload.snoozed_until),
    )


@router.post("/{action_id}/dismiss")
async def dismiss_action(action_id: int, payload: DismissPayload | None = None) -> Action:
    return _update_or_404(
        action_id,
        ActionUpdate(
            status=ActionStatus.DISMISSED,
            dismissed_reason=(payload.reason if payload else None),
        ),
    )


def _update_or_404(action_id: int, update: ActionUpdate) -> Action:
    updated = repo.update_action(action_id, update)
    if updated is None:
        raise HTTPException(status_code=404, detail="action not found")
    return updated


@router.post("/{action_id}/draft")
async def draft_action(action_id: int) -> dict[str, Any]:
    """Return a user-actionable draft for the given action.

    Shape varies by ``ActionKind``:

    * ``follow_up``    → ``{"kind": "email", "subject", "body", "mailto"}``
    * ``decision_note`` → ``{"kind": "markdown", "filename", "body"}``

    Drafting is read-only — it doesn't change the action's status.
    The user decides what to do with the artifact (open in mail
    client, save, copy, etc.).
    """
    action = repo.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="action not found")
    if action.kind is ActionKind.FOLLOW_UP:
        email = build_follow_up_email(action)
        return {
            "kind": "email",
            "subject": email.subject,
            "body": email.body,
            "mailto": email.mailto,
        }
    if action.kind is ActionKind.DECISION_NOTE:
        note = build_decision_note(action)
        return {
            "kind": "markdown",
            "filename": note.filename,
            "body": note.body,
        }
    raise HTTPException(
        status_code=400,
        detail=f"No draft generator for kind {action.kind.value!r}",
    )
