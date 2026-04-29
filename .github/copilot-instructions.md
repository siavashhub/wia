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
- Python **3.11–3.12** only. Target platform is **Windows 10/11**; do not add
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

## Pull request etiquette

- Keep PRs focused; update `docs/` when behavior or architecture changes.
- Bump `version.json` and `installer/wia.iss`'s `MyAppVersion` together when
  cutting a release; `release.yml` reads the version from the `v*` tag.
- Reference the originating issue and include a manual-test note for desktop
  changes (the agent cannot launch a WebView2 window in CI).
