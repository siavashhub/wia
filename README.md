# WIA — Work Intelligence Agent

Your AI-powered assistant for understanding and optimizing daily work across Microsoft 365.

WIA is a lightweight Windows desktop app (Python + FastAPI + pywebview) that orchestrates **Microsoft Work IQ** via MCP to reconstruct and summarize your work week, generate editable time entries, and export them to your timesheet workflow.

> **V1 feature:** [WIA Briefing](apps/wia-desktop/docs/wia-briefing.md) — weekly work summary.

## Status

🚧 Pre-alpha. V1 in active development.

## Quick start (developers)

```pwsh
# Prereqs: Python 3.11+, Node.js 20+ (for Work IQ MCP), uv (https://astral.sh/uv)
git clone <this-repo>
cd wia
uv sync
uv run wia-desktop
```

A native window opens running the WIA UI. First launch prompts you to sign in with your M365 account (Windows broker / SSO).

### Prerequisites for end users

- Windows 10/11 with WebView2 runtime (preinstalled on Win11; auto-installed on Win10).
- Node.js 20+ (for the Work IQ MCP server). The app detects and guides install if missing.
- Microsoft 365 subscription with a **Copilot license**.
- Tenant admin consent for the **Work IQ** Entra application.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```
pywebview (WebView2)  ──>  FastAPI (in-process)  ──MCP──>  Work IQ MCP server (Node)  ──>  M365
                                   │
                                   └── exposes WIA MCP server (stdio) for Copilot/other agents
```

## Roadmap

- **V1 (this release):** WIA Briefing — calendar-driven weekly summary, editable entries, CSV/clipboard export.
- **Phase 2:** Teams + email signals, React UI migration, MSIX + winget distribution.
- **Phase 3:** WIA Insights, WIA Actions, WIA Flow, proactive suggestions.

See [docs/ROADMAP.md](docs/ROADMAP.md).

## License

TBD.
