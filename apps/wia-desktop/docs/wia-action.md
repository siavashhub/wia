# WIA Actions — Product Spec

Status: Draft
Owner: WIA team
Target release: v0.4 (first slice) → v0.5+ (drafted/executed tiers)
Related: [ROADMAP.md](../../../docs/ROADMAP.md), [ARCHITECTURE.md](../../../docs/ARCHITECTURE.md)

---

## 1. Summary

**WIA Actions** turns the descriptive output of WIA Briefing into **prescriptive,
acceptable suggestions** for the user. For every weekly scan, WIA proposes a
small set of concrete next steps ("send recap to Contoso QBR attendees", "reply
to Sam's pricing thread", "block 2h focus time Thursday") derived from the same
calendar / Teams / email entries WIA already ingests via Work IQ.

Each action carries a **rationale**, a **status lifecycle** (suggested →
accepted / dismissed / snoozed / completed), and an optional **draft artifact**
(email body, `.ics`, todo). WIA never executes external side-effects in v1 —
the user reviews, copies, and sends in their native client.

## 2. Goals & non-goals

### Goals
- Surface a short, high-signal list of actions per weekly scan (target: ≤10).
- Always explain *why* an action was suggested.
- Let the user accept, dismiss, snooze, or complete actions; remember dismissals.
- Generate copy-pasteable / open-in-app draft artifacts (Tier 2).
- Expose actions over the existing MCP server so external agents (Copilot Chat,
  Claude Code) can list and update them.
- Fit cleanly into the existing layering: pure logic in `core/`, persistence in
  `storage/`, HTTP in `api/`, MCP boundary in `mcp_server/`.

### Non-goals (v1)
- No sending email, posting to Teams, or writing to Graph from WIA.
- No new auth flow. Auth stays delegated to `@microsoft/workiq`.
- No LLM dependency. v1 is rule-based; LLM enrichment is a later, opt-in flag.
- No integrations outside the M365 surface WIA already sees (Jira/SAP etc.
  belong to WIA Connect, Phase 3).
- No org-level or multi-user features.

## 3. User stories

1. **As an IC**, after my Monday briefing I want a short list of follow-ups I
   owe people, so I don't drop commitments I made in last week's meetings.
2. **As a manager**, I want WIA to flag email threads I haven't replied to in
   over a week so I can triage them.
3. **As a heavy meeting user**, I want WIA to suggest focus blocks when
   reactive work spikes week-over-week.
4. **As a Copilot Chat user**, I want to ask *"what actions does WIA have for
   me this week?"* and get the same list as the desktop app.
5. **As a privacy-conscious user**, I want to dismiss a suggestion and never
   see that pattern again until I re-enable it in settings.

## 4. UX

### Surface
A new **Actions** tab on the briefing page, next to the existing weekly
summary. Same window, no new chrome.

### Card layout
Each action renders as a card:

```
┌────────────────────────────────────────────────────────────┐
│ ✉  Send recap to Contoso QBR attendees                    │
│ Suggested because: you said "I'll send notes" in the      │
│ meeting on Tue, and no outbound email matched within 48h. │
│                                                            │
│ [ Draft email ]  [ Mark done ]  [ Snooze ▾ ]  [ Dismiss ] │
└────────────────────────────────────────────────────────────┘
```

Rules:
- **Title** is one line, verb-first.
- **Rationale** is always visible; never hidden behind a tooltip.
- **Primary action** depends on `kind` (Draft email / Open .ics / Copy todo).
- **Snooze** offers: 1 day, 3 days, next week, custom.
- **Dismiss** records the reason as a quiet learning signal (`storage/prefs.py`)
  — if a user dismisses 3+ of the same `kind` in 2 weeks, WIA suppresses that
  kind for that source pattern and shows a banner offering to re-enable it.

### Grouping & sort
- Default sort: **status (suggested → snoozed) → priority → created_at desc**.
- Group by week. Past weeks are collapsed by default.
- Empty state: *"No suggested actions this week. WIA will scan again on
  &lt;next scheduled scan&gt;."*

### Briefing integration
The briefing page shows a compact "**3 suggested actions**" pill linking to the
Actions tab. No autoplay, no modal.

## 5. Action kinds (v1)

| Kind             | Trigger                                                                  | Draft artifact     |
| ---------------- | ------------------------------------------------------------------------ | ------------------ |
| `follow_up`      | Meeting entry contains follow-up phrase ("I'll send", "let me follow up", "circle back"), no matching outbound email to attendees within 48h. | Email draft (mailto / .eml) |
| `stale_reply`    | Inbound email thread you replied to ≥7 days ago, still has activity, no reply from you since. | Email draft |
| `decision_note`  | Meeting tagged as decision-making by `core/categorization.py`, no outbound artifact within 24h. | Markdown note |
| `focus_block`    | Reactive category time ≥ X% week-over-week increase (default 25%).        | `.ics` file        |
| `recurring_tag`  | User manually edited the same auto-categorization ≥3 times.              | Prefs change suggestion |

All other kinds are deferred. Each kind is a separate suggester module so we
can ship/iterate them independently.

## 6. Tiered rollout

| Tier | Description                                  | When        |
| ---- | -------------------------------------------- | ----------- |
| 1    | Suggested only, no artifact generation       | v0.4 (MVP)  |
| 2    | Draft artifacts: `mailto:`, `.eml`, `.ics`, copy-to-clipboard | v0.5 |
| 3    | Opt-in execution via Work IQ MCP write tools | v0.6+       |

Tier 3 is gated on Work IQ exposing write scopes and an explicit per-kind opt-in
in settings. Each executed action writes an audit row and an "undo" hint.

## 7. Architecture

Fits the existing layering — no new transports, no new framework.

```
core/actions/
  __init__.py
  registry.py            # registers suggesters
  base.py                # Suggester protocol, ActionCandidate dataclass
  follow_up.py           # one module per kind
  stale_reply.py
  decision_note.py
  focus_block.py
  recurring_tag.py
  drafts/                # Tier 2 artifact generators
    email.py
    ics.py
    note.py

storage/
  actions.py             # CRUD over Action model
  models.py              # +Action, +ActionEvent

api/
  actions.py             # REST endpoints

mcp_server/
  server.py              # +list_actions, +get_action, +update_action

ui/
  app.js / index.html    # Actions tab + card component
```

### Suggester contract

```python
# core/actions/base.py
from typing import Protocol
from pydantic import BaseModel

class ActionCandidate(BaseModel):
    kind: ActionKind
    title: str
    rationale: str
    source_entry_id: str | None
    payload: dict
    dedupe_key: str          # (kind, source_entry_id) by default
    priority: int = 50       # 0 (low) – 100 (high)

class Suggester(Protocol):
    kind: ActionKind
    def suggest(self, ctx: SuggesterContext) -> list[ActionCandidate]: ...
```

`SuggesterContext` exposes read-only views of entries, prefs, prior actions
(for dedupe / dismissal learning), and the current ISO week. Suggesters are
pure functions — no DB writes, no HTTP, no MCP calls. Mirrors the existing
`core/categorization.py` style.

### Orchestrator wiring

[core/orchestrator.py](../src/wia/core/orchestrator.py) runs the scan
pipeline. After grouping + categorization, it calls
`core.actions.registry.run_all(ctx)`, dedupes candidates against existing rows
by `dedupe_key`, and persists new ones as `status="suggested"`. Existing
actions for the same key are left untouched (idempotent re-scan).

## 8. Data model

```python
# storage/models.py

class ActionKind(str, Enum):
    follow_up = "follow_up"
    stale_reply = "stale_reply"
    decision_note = "decision_note"
    focus_block = "focus_block"
    recurring_tag = "recurring_tag"
    custom = "custom"

class ActionStatus(str, Enum):
    suggested = "suggested"
    accepted = "accepted"
    snoozed = "snoozed"
    dismissed = "dismissed"
    completed = "completed"

class Action(SQLModel, table=True):
    id: str = Field(primary_key=True)              # ulid
    created_at: datetime
    updated_at: datetime
    week: str                                      # ISO week, e.g. "2026-W21"
    kind: ActionKind
    title: str
    rationale: str
    source_entry_id: str | None = Field(index=True)
    dedupe_key: str = Field(index=True, unique=True)
    payload: dict = Field(sa_column=Column(JSON))  # draft text, .ics body, etc.
    status: ActionStatus = ActionStatus.suggested
    priority: int = 50
    snoozed_until: datetime | None = None
    completed_at: datetime | None = None
    dismissed_reason: str | None = None

class ActionEvent(SQLModel, table=True):
    """Audit trail: every status change, every draft generation."""
    id: str = Field(primary_key=True)
    action_id: str = Field(foreign_key="action.id", index=True)
    at: datetime
    event: str        # "created" | "accepted" | "snoozed" | ...
    detail: dict | None = Field(default=None, sa_column=Column(JSON))
```

DB lives in the same SQLite file at `%LOCALAPPDATA%\WIA\WIA\wia.db`. Migration
is a single additive `CREATE TABLE` — no rewrites of existing rows.

## 9. HTTP API

All under `/api/actions`, async, JSON.

| Method | Path                              | Purpose                                  |
| ------ | --------------------------------- | ---------------------------------------- |
| GET    | `/api/actions?week=2026-W21`      | List actions for a week (default: current). |
| GET    | `/api/actions/{id}`               | Fetch one.                               |
| POST   | `/api/actions/{id}/accept`        | Mark accepted (user committed to do it). |
| POST   | `/api/actions/{id}/complete`      | Mark done.                               |
| POST   | `/api/actions/{id}/snooze`        | Body: `{until: iso8601}`.                |
| POST   | `/api/actions/{id}/dismiss`       | Body: `{reason?: str}`.                  |
| POST   | `/api/actions/{id}/draft`         | Returns `{content_type, body}` for the draft artifact. Tier 2. |

Every state change writes an `ActionEvent`. Endpoints are idempotent —
double-accepting is a no-op.

## 10. MCP surface

Adds to [mcp_server/server.py](../src/wia/mcp_server/server.py):

| Tool                | Purpose                                       |
| ------------------- | --------------------------------------------- |
| `list_actions`      | `{week?: str, status?: str} → Action[]`       |
| `get_action`        | `{id: str} → Action`                          |
| `update_action`     | `{id, status, snoozed_until?, reason?}`       |

This lets Copilot Chat answer *"what should I do this week?"* against WIA's
local data without exposing entries themselves. Read-only access to entries
already exists; actions follow the same pattern.

## 11. Settings & learning

Stored in [storage/prefs.py](../src/wia/storage/prefs.py):

- `actions.enabled` (bool, default true)
- `actions.kinds.<kind>.enabled` (bool, default true)
- `actions.kinds.<kind>.threshold` (per-suggester tunable, e.g. stale_reply days)
- `actions.dismissed_patterns` (list of `(kind, signature)` learned from
  repeated dismissals; suggesters consult this before emitting candidates)

A "**Re-enable suppressed suggestions**" button in settings clears
`dismissed_patterns`.

## 12. Privacy & security

- Action `payload` may contain meeting titles, draft email bodies, attendee
  names — treat the same as briefing content. **Never log payload above
  DEBUG.** Lint rule / review checklist item.
- No telemetry. No outbound network calls from action suggesters.
- Drafts written to disk (`.eml`, `.ics`) go under
  `%LOCALAPPDATA%\WIA\WIA\drafts\` with restrictive ACLs (user-only).
- Tier 3 execution requires per-kind explicit opt-in and a confirmation dialog
  with the full payload visible.

## 13. Testing

New tests under `apps/wia-desktop/tests/`:

- `test_actions_follow_up.py` — phrase detection, 48h window, dedupe.
- `test_actions_stale_reply.py` — thread state machine, day thresholds.
- `test_actions_registry.py` — dedupe across kinds, dismissal suppression.
- `test_actions_api.py` — status transitions, idempotency, snooze.
- `test_actions_orchestrator.py` — re-scan is idempotent; no duplicate rows.
- `test_actions_mcp.py` — MCP tools round-trip.

Follow existing rules: no real network, mock the MCP client, `pytest-asyncio`
auto mode, Windows-friendly paths via `tmp_path`.

## 14. Metrics (local only)

To validate value without telemetry, surface a tiny "**Actions this month**"
counter in settings:

- Suggested / accepted / completed / dismissed counts.
- Acceptance rate per kind.

Users can read these to decide which kinds to disable. We can ask for
screenshots during beta to iterate on thresholds.

## 15. Rollout plan

| Step                                       | Release |
| ------------------------------------------ | ------- |
| Data model + `follow_up` suggester + UI tab + REST | v0.4   |
| `stale_reply` + `decision_note` + dismissal learning | v0.4.x |
| Draft artifacts (`mailto:`, `.eml`, `.ics`) + MCP tools | v0.5  |
| `focus_block` + `recurring_tag`            | v0.5.x  |
| Tier 3 execution (opt-in, per kind)        | v0.6+   |

## 16. Open questions

1. Should accepting an action auto-create a `todo` row, or stay purely a
   status change? (Lean: status only in v1; a separate Todos feature is its
   own spec.)
2. Are recurring meetings deduped at the **series** level or per-instance?
   (Lean: series — one follow-up suggestion for a weekly sync, not 5.)
3. Should Tier 2 drafts be editable in-app before export, or always
   open-in-native? (Lean: open-in-native first; in-app editor is a fast-follow
   if users ask.)
4. What's the right cap on suggestions per week before the list feels noisy?
   (Proposal: hard cap 10, priority-sorted, with a "show all" expander.)
5. Do we expose `create_action` via MCP so external agents can inject custom
   actions? (Lean: no in v1 — keep WIA the sole producer; consumers can only
   read and update status.)
