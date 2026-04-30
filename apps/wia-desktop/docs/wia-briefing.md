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
   inferred blocks (`LOW` confidence).
5. **Categorize** ([`wia.core.categorization`](../src/wia/core/categorization.py)):
   - External email domains map to clients
     (`client-a.com` → *Client A*).
   - Internal items match a configurable keyword map
     (`sprint` → Internal, `design review` → Design, …).
6. Persist into SQLite (`time_entry`) keyed by `(week_of, label)` so
   manual edits survive refresh.

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
