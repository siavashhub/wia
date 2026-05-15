# WIA — Work Intelligence Agent

Your AI-powered assistant for understanding and optimizing daily work across Microsoft 365.

WIA is a lightweight Windows desktop app (Python + FastAPI + pywebview) that orchestrates **Microsoft Work IQ** via MCP to reconstruct and summarize your work week, generate editable time entries, and export them to your timesheet workflow.

> **V1 features:**
>
> - [WIA Briefing](apps/wia-desktop/docs/wia-briefing.md) — weekly work summary built from your calendar, Teams, and email signals.
> - [WIA Review](apps/wia-desktop/docs/wia-review.md) — deterministic monthly & annual roll-ups over saved briefing entries.

## Status

🚀 **v0.1.0 — first release.** WIA Briefing and WIA Review are shipped and ready for early-adopter use. Expect rapid iteration; new features and breaking changes are likely while we're in early access. See [docs/ROADMAP.md](docs/ROADMAP.md) for what's next.

## Highlights

- **Weekly briefing** — Mon–Sun summary of meetings, collaboration, and focus time, grouped by client / project / category.
- **Monthly & annual reviews** — deterministic roll-ups of saved entries (totals, top categories / labels, weekly trend, insights, talking points), surfaced in the UI and exportable to Markdown / HTML / CSV.
- **Multi-signal fusion** — calendar (HIGH confidence), Teams chats & calls (MEDIUM), substantive email threads (MEDIUM), plus inferred Admin / Focus gap-fill on weekdays (LOW), 09:00–17:00 local.
- **Editable time entries** — every row is hand-editable; manual edits are preserved across refreshes.
- **Smart categorization** — external email domains map to clients (`client-a.com` → *Client A*); internal items match a configurable keyword map (`sprint`→Internal, `design review`→Design, …).
- **Confidence scoring** — `HIGH` / `MEDIUM` / `LOW` per entry, surfaced in the UI.
- **Background scans** — opt-in scheduler kicks off a fresh briefing each Monday morning.
- **Exports** — CSV, Markdown, HTML, or system clipboard, ready to paste into your timesheet.
- **Cache-aware navigation** — Prev/Next week is instant; live MCP calls only happen on explicit refresh.
- **Embedded MCP server** — `wia-mcp` re-exposes briefings & entries to Copilot Chat and other agents over stdio.
- **No M365 sign-in code in WIA.** Auth is delegated to the `@microsoft/workiq` CLI (Microsoft first-party Entra app). WIA never sees a token. See [docs/AUTH.md](docs/AUTH.md).
- **Local-only data.** Everything lives in a private SQLite DB at `%LOCALAPPDATA%\WIA\WIA\wia.db`. No telemetry, no remote backend.

## Install (end users)

> Pre-built installers are published on the [Releases](../../releases) page once tagged `vX.Y.Z`.

1. Download `wia-setup-<version>.exe` and run it (per-user install, no admin required).
2. Make sure **Node.js 20+** is on `PATH` (WIA detects and guides install if missing).
3. Launch **WIA** from the Start menu. On first run, click **Enable Work IQ** — the `@microsoft/workiq` CLI handles the M365 sign-in flow itself.
4. Click **Refresh** to build your first briefing.

### Prerequisites

| Requirement | Notes |
| --- | --- |
| Windows 10 / 11 | x64 / ARM64-compatible |
| WebView2 runtime | Preinstalled on Win11; auto-installed on Win10 |
| Node.js 20+ | Required by `@microsoft/workiq` (invoked via `npx -y @microsoft/workiq`) |
| Microsoft 365 with Copilot license | Required by Work IQ |
| Tenant admin consent | Granted **once** for the Microsoft-published Work IQ Entra app — not for WIA |

### Verify the installer (optional)

The release workflow signs every artifact with a [GitHub build provenance attestation](https://docs.github.com/en/actions/security-guides/using-artifact-attestations-to-establish-provenance-for-builds)
via Sigstore. Anyone can confirm the installer was produced by this repo's
`release.yml` on the tagged commit (and not tampered with) using the GitHub CLI:

```pwsh
# Requires: GitHub CLI (https://cli.github.com/)
gh attestation verify .\wia-setup-0.1.0.exe --repo <owner>/wia
```

You can also cross-check against `SHA256SUMS.txt` published with the release:

```pwsh
Get-FileHash .\wia-setup-0.1.0.exe -Algorithm SHA256
```

## Quick start (developers)

```pwsh
# Prereqs: Python 3.12, Node.js 20+, uv (https://astral.sh/uv)
git clone <this-repo>
cd wia
uv sync --all-extras
uv run wia-desktop
```

A native window opens running the WIA UI. The first launch shows an **Enable Work IQ** button — click it, complete the Work IQ sign-in, then refresh.

### Common tasks

```pwsh
uv run wia-desktop              # launch the app
uv run wia-mcp                  # launch the WIA MCP server (stdio) for Copilot/agents
uv run pytest -q                # run tests
uv run ruff check .             # lint
uv run ruff format .            # format
```

To enable DevTools -> PowerShell (per-session):
```powershell
$env:WIA_DEBUG = "1"; uv run wia-desktop
```
to disable:
```powershell
Remove-Item Env:WIA_DEBUG; uv run wia-desktop
```



CI runs on `windows-latest` against Python **3.12**. Don't introduce changes that only pass on Linux/macOS.

### Expose WIA to Copilot Chat

Add to your VS Code `mcp.json`:

```json
{
  "servers": {
    "wia": { "command": "uv", "args": ["run", "wia-mcp"] }
  }
}
```

See [docs/COPILOT_MCP.md](docs/COPILOT_MCP.md) and [docs/COPILOT_AGENTS.md](docs/COPILOT_AGENTS.md).

## Architecture

```
pywebview (WebView2)  ──>  FastAPI (in-process)  ──MCP──>  @microsoft/workiq (Node)  ──>  M365
                                   │
                                   └── exposes WIA MCP server (stdio) for Copilot/other agents
```

- `wia.core.orchestrator` builds briefings: parallel `ask_work_iq` prompts → `ActivityBlock`s → grouping (merge adjacent same-source blocks, gap ≤ 5 min) → weekday gap-fill (Admin / Focus) → categorization → SQLite. Cache-aware on `refresh=false`.
- `wia.storage` owns SQLite via `sqlmodel` (`time_entry`, `user_pref`, `scan_history`).
- `wia.api` exposes `/api/health`, `/api/workiq`, `/api/briefing`, `/api/entries`, `/api/prefs`, `/api/review`, `/api/schedule`, `/api/export` over an ephemeral loopback port.
- `wia.mcp_clients.workiq` spawns `@microsoft/workiq mcp` as a stdio child process.
- `wia.mcp_server` re-exposes briefings & entries as an MCP server (`wia-mcp`).

Full diagram & data-flow walkthrough: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository layout

```
apps/wia-desktop/         # the desktop app (FastAPI + pywebview + MCP)
  src/wia/
    api/                  # HTTP routers
    core/                 # pure logic (orchestrator, grouping, categorization, scheduler, review)
    mcp_clients/          # outbound MCP (Work IQ Node CLI)
    mcp_server/           # inbound MCP (`wia-mcp`)
    storage/              # SQLite (sqlmodel)
    ui/                   # HTML + Alpine.js + Tailwind
  tests/                  # pytest (asyncio auto, Windows-friendly)
  pyinstaller.spec        # PyInstaller build config
docs/                     # ARCHITECTURE, AUTH, ROADMAP, COPILOT_*
installer/wia.iss         # Inno Setup script (driven by release.yml)
version.json              # release version source of truth
```

## Privacy & security

- **No server-side component.** WIA runs entirely on your machine.
- **No telemetry.** WIA makes no outbound network calls except via the Work IQ CLI.
- **No secrets shipped.** WIA stores no tokens; the Work IQ CLI manages its own token cache.
- User content (calendar, email, briefings) is never logged above `DEBUG`.
- The SQLite DB at `%LOCALAPPDATA%\WIA\WIA\wia.db` is user-private.
- CodeQL + Dependency Review run on every PR.

## Releasing

Bump `version.json` and `installer/wia.iss`'s `MyAppVersion` together, commit, then push a `vX.Y.Z` tag. GitHub Actions (`release.yml`) builds the PyInstaller bundle, runs Inno Setup, and uploads `wia-setup-<version>.exe` to the release.

## Roadmap

- **V1 (this release):**
  - **WIA Briefing** — calendar / Teams / email fusion, editable entries, exports, scheduler, embedded MCP server.
  - **WIA Review** — monthly & annual roll-ups built deterministically from saved briefing entries.
- **Phase 2:** React + Vite UI migration, MSIX + winget distribution, bundled Node, WIA Insights.
- **Phase 3:** WIA Actions, WIA Flow, WIA Connect (Jira / SAP / …), proactive suggestions, cross-week trends.

Full roadmap: [docs/ROADMAP.md](docs/ROADMAP.md).

## Contributing

- Use `uv` (never raw `pip` / `poetry`).
- Type-annotate new public APIs; reuse `pydantic` / `sqlmodel` models.
- Keep `core/` free of HTTP / FS / MCP concerns.
- Add tests in `apps/wia-desktop/tests/` for any change in `core`, `api`, or `storage`. Mock all network and MCP I/O.
- `ruff format` and `ruff check` must pass — both gate CI.
- Don't add Entra / MSAL code: auth is delegated to the Work IQ CLI by design.

See [AGENTS.md](AGENTS.md) for the full house rules (also consumed by GitHub Copilot's coding agent).

## License

[Apache 2.0](LICENSE) © WIA contributors. See [NOTICE](NOTICE) for attribution.
