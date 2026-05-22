"""Docs-drift guards.

These tests fail CI when the documentation in ``docs/`` (or top-level
README files) falls behind the code. They are deliberately cheap and
deterministic — no LLM calls, no network — and exist to catch the
mechanical kinds of drift:

* a new ``apps/wia-desktop/src/wia/api/<name>.py`` router that nobody
  wired into ``docs/ARCHITECTURE.md``;
* a new MCP ``Tool(name="...")`` registered in
  ``wia.mcp_server.server`` that isn't mentioned in
  ``docs/ARCHITECTURE.md`` or ``README.md``;
* a release-notes file that references a path no longer in the repo;
* an intra-repo Markdown link under ``docs/`` that points at a file
  that doesn't exist.

If a check trips falsely, prefer fixing the docs over relaxing the
test — that's the whole point.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# Resolve the repository root by walking up from this test file. We can't
# rely on ``cwd`` because pytest may be invoked from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_DIR = _REPO_ROOT / "apps" / "wia-desktop" / "src" / "wia" / "api"
_MCP_SERVER = _REPO_ROOT / "apps" / "wia-desktop" / "src" / "wia" / "mcp_server" / "server.py"
_DOCS_DIR = _REPO_ROOT / "docs"
_ARCHITECTURE_MD = _DOCS_DIR / "ARCHITECTURE.md"
_README_MD = _REPO_ROOT / "README.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _api_router_modules() -> list[str]:
    """Names of FastAPI router modules under ``wia.api``.

    Returns the basenames (``"actions"``, ``"briefing"``, ...) — skips
    ``__init__`` and any private module.
    """
    out: list[str] = []
    for p in sorted(_API_DIR.glob("*.py")):
        if p.stem.startswith("_"):
            continue
        out.append(p.stem)
    return out


_TOOL_NAME_RE = re.compile(r"""Tool\(\s*name\s*=\s*["']([a-zA-Z_][a-zA-Z0-9_]*)["']""")


def _mcp_tool_names() -> list[str]:
    """Tool names registered in the WIA MCP server."""
    text = _read(_MCP_SERVER)
    return sorted(set(_TOOL_NAME_RE.findall(text)))


_MD_LINK_RE = re.compile(
    # [label](target) — capture the target only; ignore images (![...](...)).
    r"(?<!\!)\[[^\]]+\]\(([^)\s]+)\)"
)


def _intra_repo_links(md_path: Path) -> list[tuple[str, int]]:
    """Return ``(target, line_no)`` for every Markdown link in ``md_path``
    that points at a repo-relative file (no scheme, not a bare anchor).
    """
    out: list[tuple[str, int]] = []
    for lineno, line in enumerate(_read(md_path).splitlines(), start=1):
        for target in _MD_LINK_RE.findall(line):
            # Strip URL fragment / query.
            clean = target.split("#", 1)[0].split("?", 1)[0]
            if not clean:
                continue  # pure anchor, e.g. [x](#section)
            # External / non-file schemes.
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", clean):
                continue
            # Template / placeholder targets (e.g. ``vX.Y.Z.md``).
            if any(tok in clean for tok in ("X.Y.Z", "<tag>", "{")):
                continue
            out.append((clean, lineno))
    return out


def _resolve(md_path: Path, target: str) -> Path:
    """Resolve a Markdown link target relative to its host file."""
    return (md_path.parent / target).resolve()


def _is_github_magic_path(md_path: Path, target: str) -> bool:
    """GitHub renders relative paths like ``../../releases`` or
    ``../../issues`` against the repo root on github.com, even though they
    don't resolve to anything on disk. Skip those so README links to
    the Releases / Issues / Discussions pages don't trip the check.
    """
    resolved = _resolve(md_path, target)
    try:
        resolved.relative_to(_REPO_ROOT)
    except ValueError:
        return True
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _api_router_modules())
def test_every_api_router_is_documented_in_architecture(module_name: str) -> None:
    """Each ``wia.api.<module>`` must appear in ARCHITECTURE.md.

    Easiest way to satisfy this is to add the module's row to the module-map
    table. We accept any mention of ``wia.api.<module>`` or
    ``api/<module>.py`` so the check stays flexible about exact phrasing.
    """
    arch = _read(_ARCHITECTURE_MD)
    needles = (
        f"wia.api.{module_name}",
        f"api/{module_name}.py",
        f"`/api/{module_name}`",
    )
    assert any(n in arch for n in needles), (
        f"API router 'wia.api.{module_name}' is not mentioned in docs/ARCHITECTURE.md. "
        f"Add it to the module map (looked for: {needles!r})."
    )


@pytest.mark.parametrize("tool_name", _mcp_tool_names())
def test_every_mcp_tool_is_documented(tool_name: str) -> None:
    """Each MCP ``Tool(name=...)`` must be mentioned in user-facing docs."""
    haystacks = {
        "ARCHITECTURE.md": _read(_ARCHITECTURE_MD),
        "README.md": _read(_README_MD),
        "mcp_server/server.py docstring": _read(_MCP_SERVER),
    }
    found_in = [doc for doc, text in haystacks.items() if tool_name in text]
    # The server file always mentions it (the Tool itself), so require a
    # separate hit in either ARCHITECTURE.md or README.md.
    user_facing_hits = [d for d in found_in if d != "mcp_server/server.py docstring"]
    assert user_facing_hits, (
        f"MCP tool '{tool_name}' is registered in wia.mcp_server.server but "
        f"isn't documented in ARCHITECTURE.md or README.md."
    )


def test_no_broken_intra_repo_links_in_docs() -> None:
    """Every relative Markdown link under ``docs/`` (and top-level READMEs
    that link into ``docs/``) must point at a real file."""
    md_files: list[Path] = list(_DOCS_DIR.rglob("*.md"))
    md_files.append(_README_MD)
    apps_readme = _REPO_ROOT / "apps" / "wia-desktop" / "README.md"
    if apps_readme.exists():
        md_files.append(apps_readme)

    broken: list[str] = []
    for md in md_files:
        for target, lineno in _intra_repo_links(md):
            if _is_github_magic_path(md, target):
                continue
            resolved = _resolve(md, target)
            if not resolved.exists():
                rel = md.relative_to(_REPO_ROOT)
                broken.append(f"{rel}:{lineno} -> {target}")

    assert not broken, "Broken intra-repo doc links:\n  " + "\n  ".join(broken)


def test_release_notes_filenames_are_valid_semver() -> None:
    """Files in ``docs/releases/`` must be named ``vMAJOR.MINOR.PATCH.md``.

    Catches typos before they confuse the release workflow, which looks
    for ``docs/releases/<tag>.md`` literally.
    """
    releases_dir = _DOCS_DIR / "releases"
    if not releases_dir.exists():
        pytest.skip("no docs/releases/ yet")
    pattern = re.compile(r"^v\d+\.\d+\.\d+\.md$")
    bad = [p.name for p in releases_dir.glob("*.md") if not pattern.match(p.name)]
    assert not bad, f"Release-notes files must be named vX.Y.Z.md, got: {bad}"


def test_architecture_module_map_does_not_reference_removed_modules() -> None:
    """Reverse direction: every ``wia.<dotted.path>`` mentioned in
    ARCHITECTURE.md's module map should still exist on disk.

    Keeps the table honest after refactors / deletions.
    """
    arch = _read(_ARCHITECTURE_MD)
    # Match ``wia.something`` or ``wia.something.else`` inside backticks.
    # Module map rows look like: ``| `wia.api.health` | Liveness probe |``.
    refs = set(re.findall(r"`wia\.([a-zA-Z0-9_.]+)`", arch))
    # Filter out leaf attributes (e.g. ``wia.__version__``) and known
    # type-only references that aren't modules.
    src_root = _REPO_ROOT / "apps" / "wia-desktop" / "src" / "wia"
    missing: list[str] = []
    for dotted in sorted(refs):
        if dotted.startswith("_"):
            continue
        # Try ``apps/.../wia/<dotted>.py`` or ``apps/.../wia/<dotted>/__init__.py``.
        parts = dotted.split(".")
        as_module = src_root.joinpath(*parts).with_suffix(".py")
        as_package = src_root.joinpath(*parts, "__init__.py")
        # Some entries refer to attributes inside modules (e.g. a class).
        # Walk up one component if the leaf doesn't resolve.
        if not as_module.exists() and not as_package.exists() and len(parts) > 1:
            parent = src_root.joinpath(*parts[:-1]).with_suffix(".py")
            parent_pkg = src_root.joinpath(*parts[:-1], "__init__.py")
            if parent.exists() or parent_pkg.exists():
                continue
            missing.append(dotted)
        elif not as_module.exists() and not as_package.exists():
            missing.append(dotted)
    assert not missing, (
        "ARCHITECTURE.md references modules that no longer exist:\n  "
        + "\n  ".join(f"wia.{m}" for m in missing)
    )


def test_mcp_server_docstring_lists_every_registered_tool() -> None:
    """The module docstring at the top of ``wia.mcp_server.server`` should
    enumerate every registered tool name, so reading the file is enough to
    know the surface."""
    source = _read(_MCP_SERVER)
    module = ast.parse(source)
    docstring = ast.get_docstring(module) or ""
    missing = [t for t in _mcp_tool_names() if t not in docstring]
    assert not missing, (
        "wia.mcp_server.server module docstring is missing tool names: "
        f"{missing}. Update the docstring header so the surface is "
        "documented at the top of the file."
    )
