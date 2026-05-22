"""Follow-up email draft generator."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from wia.core.types import Action


@dataclass(frozen=True)
class EmailDraft:
    """A drafted follow-up email — fully composed, never sent by WIA."""

    subject: str
    body: str
    mailto: str
    """``mailto:`` URL the UI can open directly in the OS default client.
    Recipients are intentionally empty — the user picks them in their
    mail client (WIA doesn't have access to per-meeting attendee lists
    on persisted entries)."""


_BODY_TEMPLATE = """Hi all,

Thanks for the time on {label} earlier this week. Quick recap and next steps:

Discussion
- <add the key points here>

Decisions
- <add anything we agreed on>

Next steps
- <owner> — <action> — <when>

Let me know if I missed anything.

Thanks,
"""


def build_follow_up_email(action: Action) -> EmailDraft:
    """Return a follow-up email draft for a ``follow_up`` action."""
    label = (action.payload.get("entry_label") or "our meeting").strip() or "our meeting"
    subject = f"Recap & next steps — {label}"
    body = _BODY_TEMPLATE.format(label=label)
    mailto = f"mailto:?subject={quote(subject)}&body={quote(body)}"
    return EmailDraft(subject=subject, body=body, mailto=mailto)
