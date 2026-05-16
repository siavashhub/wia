"""WIA desktop application package."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_FALLBACK_VERSION = "0.0.0-dev"


def _candidate_roots() -> list[Path]:
    """Directories to search for ``version.json``.

    In dev (source checkout) it sits at the repo root, found by walking up
    from this file. In a PyInstaller frozen build it is bundled at the
    onedir root via ``pyinstaller.spec`` and exposed through
    ``sys._MEIPASS``.
    """
    here = Path(__file__).resolve()
    roots: list[Path] = list(here.parents)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.insert(0, Path(meipass))
    # Also check next to the executable for onedir layouts where the data
    # file is staged outside _MEIPASS.
    if getattr(sys, "frozen", False):
        roots.insert(0, Path(sys.executable).resolve().parent)
    return roots


def _read_version() -> str:
    """Read version from ``version.json``.

    Tries the frozen-bundle locations first, then walks up the source tree.
    Falls back to a sentinel when the file is missing or unreadable.
    """
    for root in _candidate_roots():
        candidate = root / "version.json"
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                v = data.get("version")
                if isinstance(v, str) and v:
                    return v
            except (OSError, json.JSONDecodeError):
                continue
    return _FALLBACK_VERSION


__version__ = _read_version()
