# Architecture

```
┌────────────────────────────────────────────────┐
│ pywebview window (WebView2)                    │
│  └─ HTML + Alpine.js + Tailwind UI             │
└──────────────────────┬─────────────────────────┘
                       │ HTTP (loopback, ephemeral port)
┌──────────────────────▼─────────────────────────┐
│ FastAPI in-process                             │
│  ├─ /api/health, /api/workiq, /api/briefing,   │
│  │  /api/entries, /api/prefs, /api/review,     │
│  │  /api/schedule, /api/export, /api/actions   │
│  ├─ core.orchestrator (Work IQ → blocks →      │
│  │  entries; grouping + categorization;        │
│  │  cache-aware on refresh=false)              │
│  ├─ core.actions (suggester registry: follow_up│
│  │  + decision_note; draft generators)         │
│  └─ SQLite (time_entry, action, user_pref,     │
│     scan_history)                              │
└────────┬───────────────────────────────────────┘
         │ MCP stdio (spawns Node child process)
┌────────▼──────────────────────────────────────┐
│ @microsoft/workiq (Node, MCP server mode)     │
│  • Owns its own M365 auth (first-party Entra) │
│  • Single tool: ask_work_iq (NL → Copilot)    │
│  • WIA prompts for calendar / Teams / email   │
└───────────────────────────────────────────────┘

         ▲
         │ stdio (separate process)
┌────────┴──────────┐
│ WIA MCP server    │  exposed via `wia-mcp` for
│ (Copilot, etc.)   │  external agents
└───────────────────┘
```

## Module map

| Module | Purpose |
| --- | --- |
| `wia.main` | pywebview + FastAPI lifecycle |
| `wia.app` | FastAPI factory & routing |
| `wia.api.health` | Liveness probe |
| `wia.api.workiq` | Work IQ CLI status / install / enable endpoints |
| `wia.api.briefing` | `GET /api/briefing` and `POST /api/briefing/regenerate` |
| `wia.api.entries` | CRUD for `TimeEntry` rows (manual edits) |
| `wia.api.prefs` | User prefs (enabled signals, internal domains, keyword map) |
| `wia.api.review` | Weekly review summary endpoint |
| `wia.api.schedule` | Scheduler config + run-now + scan history |
| `wia.api.export` | CSV / Markdown / HTML / clipboard exports |
| `wia.api.updates` | Auto-update check against GitHub Releases |
| `wia.api.actions` | WIA Actions CRUD + `/draft` artifact endpoint |
| `wia.core.types` | Pydantic domain models (`ActivityBlock`, `TimeEntry`, `Briefing`, `Action`, `Confidence`, `Source`) |
| `wia.core.week` | Mon–Sun week math and weekday iteration |
| `wia.core.grouping` | Merge adjacent same-source blocks; gap-fill weekday Admin/Focus |
| `wia.core.categorization` | Rule-based labeling (external-domain → client, keyword fallback) |
| `wia.core.orchestrator` | End-to-end briefing build (cache-aware); runs action suggesters after entry merge |
| `wia.core.scheduler` | Background weekly scan trigger |
| `wia.core.review` | Weekly review aggregation |
| `wia.core.actions` | Suggester registry (`follow_up`, `decision_note`) + draft generators (`drafts/email.py`, `drafts/note.py`) |
| `wia.mcp_clients.workiq` | Work IQ MCP stdio client + CLI probe/enable |
| `wia.mcp_server.server` | WIA's exposed MCP server (`wia-mcp`) — tools: `get_weekly_briefing`, `list_time_entries`, `export_entries_csv`, `list_actions`, `update_action` |
| `wia.storage` | SQLite persistence (`entries`, `actions`, `prefs`, `scan_history`) |

## Authentication

WIA does **no** M365 sign-in. The `@microsoft/workiq` CLI handles auth via Microsoft's first-party Work IQ Entra app (admin-consented once per tenant). WIA only spawns the CLI as a child process. See [AUTH.md](AUTH.md).

## Data flow (briefing)

1. UI calls `GET /api/briefing?refresh=<bool>&week_of=<YYYY-MM-DD>`.
2. Orchestrator computes the Mon–Sun bounds for the requested week.
3. **Cache short-circuit**: when `refresh=false`, the orchestrator never spawns Work IQ. If cached entries exist for the week it returns them with `status=ok`; otherwise it returns an empty `status=no-signals` briefing so the UI can show the empty state. This keeps Prev/Next navigation cheap.
4. On `refresh=true`, the orchestrator reads the user's enabled signals from prefs (`calendar`, `teams`, `email`) and fans out parallel calls to the Work IQ MCP client via `asyncio.gather`.
5. The MCP client spawns `@microsoft/workiq mcp` over stdio. Work IQ exposes a single natural-language tool, `ask_work_iq`. WIA sends one prompt per signal (calendar / Teams / email) that demands a strict JSON shape, then `json.loads` the text content of the response.
6. Each parsed event is normalized to an `ActivityBlock`:
   - Calendar → `source=CALENDAR`, `confidence=HIGH`.
   - Teams → `source=TEAMS`, `confidence=MEDIUM`.
   - Email → `source=EMAIL`, `confidence=MEDIUM`.
   Malformed events are dropped individually. If every signal raised, the briefing returns `status=workiq-not-enabled`.
7. `grouping.merge_blocks` collapses adjacent same-source same-title blocks (gap ≤ 5 min), unioning participants. Then — only if at least one real block exists, and only on weekdays (Mon–Fri) — `grouping.fill_gaps` inserts inferred `Admin / Follow-up` and `Focus time` blocks (`source=INFERRED`, `confidence=LOW`) inside the 09:00–17:00 local window.
8. `categorization.aggregate_entries` buckets blocks by `(label, category)`:
   - External email domain (any participant whose domain is **not** in `internal_domains`) wins as the category, e.g. `client-a.com` → `Client A`.
   - Otherwise the title is matched against the keyword map (`sprint→Internal`, `design review→Design`, …).
   - Inferred blocks become `Admin` category entries.
   Each entry's confidence is the **lowest** of its constituent blocks (HIGH > MEDIUM > LOW).
9. `entries_repo.replace_week` deletes only **non-user-edited** rows for the week and inserts the fresh aggregation; manual edits survive untouched.
10. The orchestrator re-reads entries, computes `BriefingTotals` and top work areas, and returns the `Briefing` payload to the UI.

When the briefing is served from cache (no live blocks), totals are derived from entry confidence: `HIGH→meetings`, `MEDIUM→collaboration`, `LOW`/label-prefix `focus→focus`.

## Confidence scoring

| Level | Meaning | Source |
| --- | --- | --- |
| `HIGH` | Explicit calendar event | `Source.CALENDAR` |
| `MEDIUM` | Inferred from collaboration signal (Teams chats/calls, substantive email threads) | `Source.TEAMS`, `Source.EMAIL` |
| `LOW` | Gap-fill inference (`Admin / Follow-up`, `Focus time`) | `Source.INFERRED` |

`TimeEntry.confidence` collapses to the lowest level among its constituent blocks, so a calendar meeting that picked up a co-occurring Teams thread reports `MEDIUM`. Cached briefings use confidence as the source proxy because `TimeEntry` rows don't persist `Source`.

## WIA Actions

The actions layer ([core/actions/](../apps/wia-desktop/src/wia/core/actions/), [api/actions.py](../apps/wia-desktop/src/wia/api/actions.py), [storage/actions.py](../apps/wia-desktop/src/wia/storage/actions.py)) turns the briefing into a small set of concrete, user-actionable suggestions. See [wia-action.md](../apps/wia-desktop/docs/wia-action.md) for the full product spec.

- **Suggesters** are pure functions over a `SuggesterContext` (`week_of`, `entries`, `dismissed_dedupe_keys`). Each produces zero or more `ActionCandidate`s.
  - `follow_up` — fires on entries whose notes mention sending recap / minutes / next steps, or whose labels look like a kickoff / debrief / retro / planning / QBR.
  - `decision_note` — fires on entries whose notes mention a decision (decided / agreed / approved / sign-off / go-no-go), or whose labels look like a decision / review / approval.
- The orchestrator runs the suggester registry after `entries_repo.merge_week`. `storage.actions.upsert_candidates` is dedupe-key based (`"{kind}:{week_of}:{entry_id}"`) and never overwrites user-set status — re-running a scan only refreshes cosmetic fields (title, rationale, payload) on already-suggested rows.
- **Status machine:** `suggested → {accepted, snoozed, dismissed, completed}`. Dismissed dedupe keys are fed back into the next suggester run so a dismissed card never resurfaces for the same `(kind, week, entry)`.
- **Drafts** are read-only artifact generators ([drafts/email.py](../apps/wia-desktop/src/wia/core/actions/drafts/email.py), [drafts/note.py](../apps/wia-desktop/src/wia/core/actions/drafts/note.py)). `POST /api/actions/{id}/draft` returns an email shape (`subject`/`body`/`mailto:` URL) for `follow_up` or a Markdown shape (`filename`/`body`) for `decision_note`. Drafting never mutates status — the user decides what to do with the artifact.
- The UI Actions tab lazy-loads from `GET /api/actions` and offers Draft / Accept / Snooze / Dismiss / Mark done. Email drafts open via `mailto:` (clipboard backup); Markdown drafts route through the pywebview `save_file` bridge with a Blob URL fallback.
- The MCP server (`wia-mcp`) re-exposes the same surface to external agents via `list_actions` and `update_action`.
