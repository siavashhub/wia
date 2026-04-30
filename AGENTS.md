# AGENTS.md

Guidance for AI coding agents (GitHub Copilot coding/review agents, Claude
Code, Cursor, etc.) working in this repository. Mirrors
[.github/copilot-instructions.md](.github/copilot-instructions.md) for tools
that read `AGENTS.md`.

## Build & test commands

```pwsh
uv sync --all-extras            # install / refresh deps
uv run ruff format --check .    # formatting gate (CI)
uv run ruff check .             # lint gate (CI)
uv run pytest -q                # tests (Windows-friendly, asyncio auto)
uv run wia-desktop              # launch the app locally
uv run wia-mcp                  # launch the MCP server (stdio)
```

CI runs on `windows-latest` against Python 3.12. Do not introduce
Linux/macOS-only assumptions in runtime code.

## Repo layout

| Path | Purpose |
| --- | --- |
| `apps/wia-desktop/src/wia/` | Application code (FastAPI + pywebview + MCP). |
| `apps/wia-desktop/src/wia/core/` | Pure domain logic (grouping, categorization, orchestrator). |
| `apps/wia-desktop/src/wia/api/` | FastAPI HTTP endpoints. |
| `apps/wia-desktop/src/wia/storage/` | SQLite persistence (`sqlmodel`). |
| `apps/wia-desktop/src/wia/mcp_clients/` | Outbound MCP (Work IQ Node CLI). |
| `apps/wia-desktop/src/wia/mcp_server/` | Inbound MCP (`wia-mcp`). |
| `apps/wia-desktop/tests/` | Pytest suite. |
| `installer/wia.iss` | Inno Setup script (driven by `release.yml`). |
| `apps/wia-desktop/pyinstaller.spec` | PyInstaller build config. |

## House rules

- Use `uv`, not `pip`/`poetry`.
- Type-annotate new public APIs; reuse `pydantic` / `sqlmodel` models.
- Keep `core/` free of HTTP, FS, and MCP concerns.
- WIA performs **no** M365 sign-in itself — auth is delegated to the
  `@microsoft/workiq` CLI. Do not add Entra / MSAL code.
- Add tests in `apps/wia-desktop/tests/` for any change in `core`, `api`, or
  `storage`. Mock all network and MCP I/O.
- Don't log user content (calendar, email, briefings) above DEBUG level.
- When cutting a release: bump `version.json` and `installer/wia.iss` together,
  then push a `vX.Y.Z` tag — `release.yml` does the rest.

## What not to do

- Don't add a server-side component, telemetry endpoint, or remote DB.
- Don't migrate to a JS framework or replace pywebview without an architecture
  issue first.
- Don't commit secrets, tenant IDs, or signed binaries.
- Don't bypass `ruff format` / `ruff check` — both are required to pass CI.
