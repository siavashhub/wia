# Roadmap

A snapshot of where WIA is and where it's going. Versions in parentheses are
the releases the feature first shipped in.

## Shipped

### WIA Briefing — v0.1 → v0.2.1
- Calendar, Teams, and Email ingestion via the `@microsoft/workiq` MCP CLI
  (auth fully delegated; WIA has no M365 sign-in code).
- Rule-based grouping (`core.grouping`) and a category-umbrella model
  (`core.categorization`) that merges related signals into one entry.
- Editable, mergeable time entries: manual add, per-entry notes, inline
  signal tags, duration edits, category-group delete.
- ISO-8601 weeks, configurable week-start preference.
- High-impact keyword/category filtering; private-event exclusion.
- Organization auto-detect from the signed-in Work IQ identity.
- Exports: CSV, Markdown, HTML, clipboard.
- pywebview + WebView2 desktop shell with a splash, dark-mode-by-class,
  global Preferences and Scans slide-overs.
- Background weekly scan scheduler + scan-history panel
  (`core.scheduler`, `storage.scan_history`, `/api/schedule`).
- Auto-update banner that points at the latest GitHub Release
  (`core.updates`, `/api/updates`).
- Daily-rotating logs at `%LOCALAPPDATA%\WIA\WIA\logs\wia.log` with
  configurable retention; `/api/health/logs` exposes the active file.
- GitHub Releases distribution via Inno Setup; tag-driven release
  pipeline (push `vX.Y.Z` → `release.yml` stamps `version.json` and
  the installer).

### WIA Review — v0.2.1
- Monthly / yearly review aggregation (`core.review`, `/api/review`).
- Category breakdown, top initiatives, high-impact items, weekly-trend
  chart, period-over-period deltas, insights, and 1:1 talking points
  grouped by section.
- Markdown export of the Review.

### WIA Actions (Tier 1 + Tier 2) — v0.3.0
- New top-level Actions tab next to Briefing and Review.
- Rule-based suggester registry (`core.actions`) with two built-ins:
  - `follow_up` — meetings whose notes mention recap / minutes / next
    steps, or whose label looks like a kickoff / debrief / retro /
    planning / QBR.
  - `decision_note` — meetings whose notes mention a decision (decided /
    agreed / approved / sign-off / go-no-go), or whose label looks like
    a decision / review / approval.
- Status workflow: `suggested → accepted | snoozed | dismissed |
  completed`. Re-scans never overwrite user-set status; dismissed dedupe
  keys are suppressed on the next run.
- Draft generators: `follow_up` opens `mailto:` with a templated subject
  and body (clipboard backup); `decision_note` saves a Markdown note via
  the pywebview save bridge with a Blob URL fallback.
- `POST /api/actions/{id}/draft` is intentionally read-only — preview
  without committing the action.
- Spec: [wia-action.md](../apps/wia-desktop/docs/wia-action.md).

### `wia-mcp` server — v0.1 → v0.3.0
- A second console entry point that re-exposes WIA's data to external
  agents (e.g., GitHub Copilot Chat) over stdio.
- Tools: `get_weekly_briefing`, `list_time_entries`, `export_entries_csv`,
  `list_actions`, `update_action`.

## In progress

Nothing currently in flight. Next slice is up for grabs.

## Planned

### Near term
- **`stale_reply` suggester.** Surface inbound emails awaiting your
  reply. Blocked on raw per-message persistence — WIA today only stores
  aggregated `TimeEntry` rows. Needs a new message store + Work IQ
  prompt before the suggester itself is meaningful.
- **MSIX packaging + winget submission.** Replace (or complement) the
  Inno Setup installer for friction-free updates.
- **Bundled Node.js runtime.** Remove the external Node prerequisite for
  `@microsoft/workiq` so the installer is fully self-contained.
- **Automated coverage for the Actions tab.** Currently relies on a
  human smoke pass before tagging; worth a Playwright / WebView2 harness.

### Mid term
- **WIA Insights — patterns and recommendations.** Go beyond the Review
  tab's per-period insights to cross-period pattern detection (recurring
  overruns, low-impact meeting load, focus-time erosion, etc.).
- **Cross-week trends and anomaly detection** layered on top of the
  Review weekly-trend chart.
- **Action backfill / re-run.** Today actions are only generated as a
  side effect of a briefing scan; let users re-run suggesters
  independently and across past weeks.

### Long term
- **WIA Actions Tier 3 (executed).** Sending mail, filing tasks, posting
  Teams messages — gated behind explicit per-tenant opt-in and an audit
  trail.
- **WIA Flow — workflow orchestration.** Chain actions into multi-step
  flows.
- **WIA Connect — external integrations.** Jira, ServiceNow, SAP, etc.,
  as both signal sources and action targets.
- **Org-level analytics.** Admin-opt-in aggregate views across a team or
  organization.
