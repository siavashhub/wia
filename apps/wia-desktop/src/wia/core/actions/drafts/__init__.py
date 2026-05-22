"""Draft-artifact generators for WIA Actions.

Each action ``kind`` maps to one generator that turns the persisted
action (title + rationale + payload) into a user-actionable artifact:

* ``follow_up``  → :class:`EmailDraft`     (subject, body, ``mailto:`` URL)
* ``decision_note`` → :class:`NoteDraft`   (filename, Markdown body)

Generators are pure — no FS, no HTTP, no MCP. The API layer decides
how to deliver the artifact (return JSON, the UI handles delivery via
``mailto:`` / clipboard / pywebview save_file).
"""

from wia.core.actions.drafts.email import EmailDraft, build_follow_up_email
from wia.core.actions.drafts.note import NoteDraft, build_decision_note

__all__ = [
    "EmailDraft",
    "NoteDraft",
    "build_decision_note",
    "build_follow_up_email",
]
