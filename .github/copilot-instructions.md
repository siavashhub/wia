# Copilot instructions for WIA

These instructions are loaded automatically by GitHub Copilot's **coding agent**
and **code review agent** when they operate on this repository. Keep entries
short and factual.

## Project shape

- Windows desktop app: **pywebview** (WebView2) front-end + **FastAPI** backend
  in-process + an **MCP** client that drives the `@microsoft/workiq` Node CLI.
- Also ships an MCP **server** (`wia-mcp`) that re-exposes briefings/entries to
  external agents (e.g. Copilot Chat). See [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).
- Monorepo managed with **uv workspaces**. Application code lives in
  [apps/wia-desktop/src/wia](../apps/wia-desktop/src/wia/).
- Python **3.12** only. Target platform is **Windows 10/11**; do not add
  POSIX-only assumptions to runtime code.

## Toolchain

- Always use `uv` — never raw `pip`, `python -m venv`, or `poetry`.
- Install / refresh deps: `uv sync --all-extras`.
- Run the app: `uv run wia-desktop`.
- Run the MCP server: `uv run wia-mcp`.
- Lint: `uv run ruff check .` Format: `uv run ruff format .`
- Tests: `uv run pytest -q` (config in root `pyproject.toml`, tests in
  `apps/wia-desktop/tests`).
- CI runs on `windows-latest` against Python 3.11 and 3.12. Do not introduce
  changes that only pass on Linux.

## Coding conventions

- Type-annotate all new public functions; prefer `pydantic` models for
  payloads and `sqlmodel` for persistence (existing patterns in
  [apps/wia-desktop/src/wia/storage](../apps/wia-desktop/src/wia/storage/)).
- Use `httpx.AsyncClient` for HTTP and `asyncio` for I/O. FastAPI handlers are
  async unless they are trivially synchronous.
- Keep modules cohesive: `core/` is pure logic, `api/` is HTTP, `mcp_clients/`
  and `mcp_server/` are transport boundaries, `storage/` owns SQLite. Don't
  cross those layers.
- Don't introduce a new database, web framework, JS framework, or auth flow
  without an issue describing the migration. The app intentionally has **no**
  M365 sign-in code — auth is delegated to `@microsoft/workiq`.
- Follow existing Ruff config (`select = E,F,W,I,B,UP,SIM,RUF`,
  `line-length = 100`). Run the formatter before committing.

## Testing expectations

- Add or update tests in `apps/wia-desktop/tests/` for any behavior change in
  `core/`, `api/`, or `storage/`.
- Use `pytest-asyncio` (already configured, `asyncio_mode = "auto"`).
- Do not make real network or M365 calls in tests; mock the MCP client and
  HTTP layer.
- Keep test runs Windows-friendly: avoid `/tmp`, fork-only fixtures, or
  POSIX-signal handling. Use `tmp_path` and `platformdirs`.

## Security

- Treat the SQLite DB at `%LOCALAPPDATA%\WIA\WIA\wia.db` as user-private. Do
  not log row contents at INFO or higher.
- Never commit secrets, tokens, or sample tenant IDs. The app has no server
  side and ships no secrets.
- For any new dependency, prefer pinned major versions and well-maintained
  packages. CodeQL + Dependency Review run on every PR — fix high-severity
  findings before requesting review.

## Documentation obligations

Documentation is treated as code. A PR that adds or changes a user-visible
surface without updating the matching docs is incomplete and will fail CI
(see `apps/wia-desktop/tests/test_docs_drift.py`).

When you change code under these paths, you **must** update the listed docs
in the same PR:

| Code change | Docs to touch |
| --- | --- |
| New / removed module under `apps/wia-desktop/src/wia/` | [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) module map |
| New router in `apps/wia-desktop/src/wia/api/` | [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) module map + diagram |
| New / renamed `Tool(name=...)` in `wia.mcp_server.server` | [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) **and** the module docstring at the top of `server.py` |
| New top-level feature / tab | [docs/ROADMAP.md](../docs/ROADMAP.md): move it from Planned to Shipped with the release it lands in |
| Shipping a release tag `vX.Y.Z` | Create `docs/releases/vX.Y.Z.md` *before* pushing the tag — `release.yml` will refuse to publish without it |
| User-visible behaviour change | [README.md](../README.md) and [apps/wia-desktop/README.md](../apps/wia-desktop/README.md) if they mention the affected surface |

Link to files using workspace-relative paths so the docs-drift link checker
can verify them. Do not break links into `docs/releases/`, `docs/AUTH.md`,
or any spec under `apps/wia-desktop/docs/`.

## Pull request etiquette

- Keep PRs focused; update `docs/` when behavior or architecture changes.
- To cut a release, just push a `vX.Y.Z` git tag. The tag is the single source
  of truth: `release.yml` stamps `version.json` and passes the version to
  Inno Setup. Do not bump `version.json` or `installer/wia.iss` by hand.
- Reference the originating issue and include a manual-test note for desktop
  changes (the agent cannot launch a WebView2 window in CI).
