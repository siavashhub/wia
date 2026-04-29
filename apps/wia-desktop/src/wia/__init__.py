"""WIA desktop application package."""

from __future__ import annotations

import json
from pathlib import Path

_FALLBACK_VERSION = "0.1.0"


def _read_version() -> str:
    """Read version from ``version.json`` at the repo root.

    Walks up from this file looking for a ``version.json``. Falls back to a
    hard-coded constant when packaged (e.g. PyInstaller frozen build) and the
    file is not present on disk.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "version.json"
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                v = data.get("version")
                if isinstance(v, str) and v:
                    return v
            except (OSError, json.JSONDecodeError):
                break
    return _FALLBACK_VERSION


__version__ = _read_version()
