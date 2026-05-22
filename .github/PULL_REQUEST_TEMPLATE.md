<!--
WIA pull request template. Keep the checklist; fill in or strike through.
-->

## Summary

<!-- 1–3 sentences. What changes for the user / developer? Reference the
originating issue with `Fixes #N` / `Refs #N` if applicable. -->

## Type of change

- [ ] Bug fix
- [ ] New feature / user-visible surface
- [ ] Refactor / internal cleanup
- [ ] Docs only
- [ ] Release prep (`docs/releases/vX.Y.Z.md`, ROADMAP move)

## Verification

- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] `uv run pytest -q`
- [ ] Manual Windows smoke test (for desktop / UI changes — CI can't drive
      WebView2)

## Docs touched

`apps/wia-desktop/tests/test_docs_drift.py` will fail CI if these aren't
kept in sync. Strike through rows that don't apply.

- [ ] **Module map** — added / updated in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
      for any new module under `apps/wia-desktop/src/wia/`.
- [ ] **API surface** — new routers in `wia.api.*` appear in the module
      map and the diagram.
- [ ] **MCP tools** — new `Tool(name=...)` entries appear in
      [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) **and** the module
      docstring at the top of `wia/mcp_server/server.py`.
- [ ] **Roadmap** — features moved between Planned / In progress / Shipped
      in [docs/ROADMAP.md](docs/ROADMAP.md) to reflect this PR.
- [ ] **README** — [README.md](README.md) and
      [apps/wia-desktop/README.md](apps/wia-desktop/README.md) updated if
      a user-visible surface changed.
- [ ] **Release notes** — if this PR will be the last one before tagging
      `vX.Y.Z`, `docs/releases/vX.Y.Z.md` exists (else `release.yml` will
      refuse to publish).
