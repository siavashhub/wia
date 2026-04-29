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
│  │  /api/entries, /api/export                  │
│  ├─ core.orchestrator (Work IQ → blocks →      │
│  │  entries; grouping + categorization)        │
│  └─ SQLite (activity_block, time_entry, prefs) │
└────────┬───────────────────────────────────────┘
         │ MCP stdio (spawns Node child process)
┌────────▼──────────────────────────────────────┐
│ @microsoft/workiq (Node, MCP server mode)     │
│  • Owns its own M365 auth (first-party Entra) │
│  • Talks to Microsoft Copilot → Graph         │
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
| `wia.api.*` | HTTP endpoints (`workiq` status/enable, briefing, entries, export) |
| `wia.core.types` | Pydantic domain models |
| `wia.core.grouping` | Merge / gap-fill activity blocks |
| `wia.core.categorization` | Rule-based labeling |
| `wia.core.orchestrator` | End-to-end briefing build |
| `wia.mcp_clients.workiq` | Work IQ MCP stdio client + CLI probe/enable |
| `wia.mcp_server.server` | WIA's exposed MCP server |
| `wia.storage` | SQLite persistence |

## Authentication

WIA does **no** M365 sign-in. The `@microsoft/workiq` CLI handles auth via Microsoft's first-party Work IQ Entra app (admin-consented once per tenant). WIA only spawns the CLI as a child process. See [AUTH.md](AUTH.md).

## Data flow (briefing)

1. UI calls `GET /api/briefing?refresh=true`.
2. Orchestrator computes Mon–Fri bounds.
3. Work IQ MCP client spawns the Node server, calls `calendar.list`.
4. Events normalize → `ActivityBlock` (HIGH confidence, source=CALENDAR).
5. `grouping.merge_blocks` collapses adjacencies; `fill_gaps` adds inferred Admin/Focus blocks (LOW).
6. `categorization.aggregate_entries` produces grouped `TimeEntry` rows (label, category, hours, confidence).
7. Repository persists entries for the week (preserves user-edited rows).
8. Briefing payload returns to UI: totals, top areas, entries, blocks.

## Confidence scoring

- HIGH — explicit calendar event.
- MEDIUM — multi-signal inference (reserved for Phase 2 with Teams/email).
- LOW — gap-fill inference (Admin / Focus time).
