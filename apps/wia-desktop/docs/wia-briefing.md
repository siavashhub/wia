# WIA Briefing — product spec

> Status: shipped in v0.1.0. Iterating during early-adopter use.

## Summary

**WIA Briefing** reconstructs your work week (Mon–Sun) from Microsoft 365
signals exposed by [`@microsoft/workiq`](https://www.npmjs.com/package/@microsoft/workiq)
and turns it into a set of editable, exportable time entries. It is the
primary surface of WIA: you open the app, look at last week, edit a few
rows, and export to your timesheet.

## Goals

- One-screen view of how the week was actually spent.
- Single-click refresh; cache-aware navigation between weeks.
- Hand-editable rows that survive subsequent refreshes.
- No M365 sign-in code in WIA — auth lives in the Work IQ CLI.

## Inputs (signals)

Pulled in parallel from Work IQ via MCP.

| Source | Confidence | Notes |
| --- | --- | --- |
| Calendar | `HIGH` | Accepted/tentative meetings, organizer + attendees. |
| Teams chats & calls | `MEDIUM` | Substantive threads; 1:1 chatter is filtered. |
| Email threads | `MEDIUM` | Threads with ≥ N replies or ≥ M minutes drafting. |
| Inferred Admin / Focus | `LOW` | Weekday gap-fill 09:00–17:00 local when nothing else is recorded. |

## Pipeline

Implemented in [`wia.core.orchestrator`](../src/wia/core/orchestrator.py):

1. Fan out parallel `ask_work_iq` MCP prompts per signal.
2. Convert results to `ActivityBlock`s (timestamped, sourced, sized).
3. **Group** adjacent same-source blocks where the gap ≤ 5 min
   ([`wia.core.grouping`](../src/wia/core/grouping.py)).
4. **Gap-fill** weekdays 09:00–17:00 local with `Admin` / `Focus`
   inferred blocks (`LOW` confidence). Skipped per day when the
   existing block hours already meet or exceed a standard work day
   (8h) — a day full of short Teams / email engagement doesn't need
   synthetic Admin layered on top.
5. **Categorize** ([`wia.core.categorization`](../src/wia/core/categorization.py)):
   - External email domains map to clients
     (`client-a.com` → *Client A*).
   - Internal items match a configurable keyword map
     (`sprint` → Internal, `design review` → Design, …).
6. Persist into SQLite (`time_entry`) keyed by `(week_of, label)` so
   manual edits survive refresh. After applying the incoming entries,
   `merge_week` runs an **orphan sweep**: any prior non-edited row
   that the current scan did not match (by block-id overlap or
   `(label, category)`) is dropped. This is the only way to keep a
   clean week in builds where activity blocks aren't persisted with
   stable ids — without it, every rescan whose normalised title or
   category drifted slightly would leave a duplicate row behind and
   weekly totals would creep up forever. The sweep is skipped when
   the scan returned zero entries so a failed signal can't wipe the
   week, and user-edited / manual rows are partitioned out first and
   never touched.

Between steps 1 and 2 the orchestrator drops any fetched block whose
title or participant matches a user-configured **excluded keyword**
(case-insensitive substring). Inferred Admin / Focus blocks are never
filtered. Edit the list from the Briefing toolbar; it persists in
`user_pref` and applies to the next scan.

### Noise-reduction ingest filters (v0.3.1)

A set of attendance-aware filters run in the same ingest pass to drop
calendar meetings the user demonstrably did not attend. All four are
on by default and editable from **Settings → Exclude**:

- **Declined meetings** — drops blocks whose `responseStatus` is
  `declined`.
- **No-response meetings** — drops blocks whose `responseStatus` is
  `notResponded`.
- **Optional in large meetings** — drops blocks where the user was an
  Optional attendee and the total invitee count meets a configurable
  threshold (default 20).
- **Min email thread (h)** — drops `EMAIL` blocks shorter than the
  configured duration (default 0.1h). Set to 0 to disable.
- **Passive Teams threads** — drops `TEAMS` blocks where Work IQ
  returns `iParticipated=false` (channel-style threads the user only
  scrolled past, with no message sent, reaction posted, or call audio
  joined). Default on. Blocks missing the field are kept and logged.

Organizer-owned events are *never* dropped by the attendance filters.
Blocks that arrive without the required metadata (Copilot occasionally
omits `responseStatus` / `iParticipated` even when the prompt asks for
them) are kept and the orchestrator logs a `WARNING` so the user can
see how many unsuitable blocks slipped through.

### Title normalisation

To keep recurring conversations and workshops from spawning a fresh
row every scan, `_event_to_block` rewrites two patterns at ingest:

- Teams and Email titles have a *single trailing parenthetical*
  stripped (`O.U.C.H. group chat (Mon recap)` → `O.U.C.H. group chat`).
  Nested parens are left alone so genuinely-different conversations
  stay distinct.
- Calendar titles have date-stamped pipe segments and `- option N` /
  `- Wkshop N` suffixes stripped iteratively. Pipe segments that don't
  contain a digit are preserved.

The original title is preserved verbatim in
`block.metadata['original_title']` whenever normalisation rewrote it.

The categorizer is also driven by an **Additional internal domains**
list (Settings → Organization). Email domains in that list are treated
as part of the user's own organization, so a meeting with a
`@github.com` participant for a Microsoft user collapses to *Internal*
rather than spawning a bogus "Github" client bucket. Microsoft users
get `github.com`, `linkedin.com`, `xbox.com`, and `ghe.com` seeded by
default; the list is fully editable.

`refresh=false` short-circuits the pipeline and serves the last cached
briefing for the requested week — Prev/Next navigation does not call
Work IQ.

## Output (`Briefing`)

Defined in [`wia.core.types`](../src/wia/core/types.py).

| Field | Meaning |
| --- | --- |
| `week_start` / `week_end` | ISO dates (Mon, Sun). |
| `totals` | Aggregated `total`, `meetings`, `focus`, `collaboration` hours. |
| `top_work_areas` | Top 5 categories/clients by hours. |
| `entries` | Editable rows with per-day breakdown, label, category, confidence. |
| `blocks` | The pre-grouped activity blocks (for the timeline view). |
| `generated_at` | UTC timestamp of last refresh. |

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/briefing?week_of=YYYY-MM-DD&refresh=false` | Current/cached briefing. |
| `GET /api/entries?week_of=…` | Just the editable rows. |
| `PUT /api/entries/{id}` | Persist an edit. |
| `POST /api/export/{format}` | CSV / Markdown / HTML / clipboard. |
| `GET /api/schedule` / `PUT /api/schedule` | Background scan settings. |
| `GET /api/prefs` / `PUT /api/prefs` | Internal-domain list, keyword map, enabled signals. |

Routers live under [`apps/wia-desktop/src/wia/api/`](../src/wia/api/).

## Editing & confidence

- Every row in the UI is editable: label, category, hours, per-day
  hours.
- Edits set `manual=true` on the row; later refreshes skip rows where
  `manual` is set so user input is never overwritten.
- Confidence is surfaced as a chip in the UI (`HIGH` / `MEDIUM` / `LOW`)
  to flag rows worth double-checking before export.

## Background scans

Optional scheduler ([`wia.core.scheduler`](../src/wia/core/scheduler.py))
runs a refresh on a configurable cadence (default: Monday morning).
Disabled by default; toggle via the *Schedule* panel.

## Exports

CSV, Markdown, HTML, and clipboard. Produced in
[`wia.api.export`](../src/wia/api/export.py); used both by the UI
buttons and by the embedded MCP server (`wia-mcp`) so external agents
(Copilot Chat, …) can pull the same content.

## Out of scope (for now)

- Direct timesheet submission to third-party systems (planned: WIA
  Connect in Phase 3).
- Cross-week trend analysis (covered by [WIA Review](wia-review.md)).
- LLM-generated entry summaries (we keep entry titles deterministic so
  manual edits remain meaningful).

## Related

- [WIA Review](wia-review.md) — monthly / annual roll-ups over saved
  briefings.
- [Architecture](../../../docs/ARCHITECTURE.md) — full pipeline diagram.
- [Auth](../../../docs/AUTH.md) — why WIA has no Entra / MSAL code.
- [Roadmap](../../../docs/ROADMAP.md) — what's next.
