"""Windows single-instance enforcement.

Acquires a named kernel mutex at startup so a second ``wia-desktop`` launch
(double-clicking the shortcut while the app is already running) becomes a
focus-the-existing-window operation instead of spinning up a duplicate
FastAPI server + MCP child + SQLite writer.

Win32 only — ``main.run()`` is the only caller, and the repo is Windows-only
at runtime. On non-Windows platforms (developer machines, CI on Linux for
linting) the helpers degrade to a no-op so imports stay safe.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Public so tests can reference the exact name without re-deriving it.
MUTEX_NAME = "Global\\WIA.WorkIntelligenceAgent.SingleInstance"

_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9


@dataclass
class InstanceLock:
    """Result of :func:`acquire`.

    ``acquired`` is False when another WIA process already holds the mutex.
    ``handle`` is the raw mutex handle when acquired (must be kept alive
    for the lifetime of the process); ``None`` otherwise. Callers should
    retain the returned lock for the whole process lifetime — letting it
    be garbage-collected closes the handle and releases the mutex.
    """

    acquired: bool
    handle: int | None = None


def acquire(name: str = MUTEX_NAME) -> InstanceLock:
    """Try to acquire the single-instance mutex.

    Returns an :class:`InstanceLock` with ``acquired=True`` when this is
    the first instance, ``acquired=False`` when another instance already
    owns the mutex. On non-Windows platforms always returns
    ``acquired=True`` (no-op).
    """
    if not sys.platform.startswith("win"):
        return InstanceLock(acquired=True, handle=None)

    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    # CreateMutexW(lpMutexAttributes, bInitialOwner, lpName)
    handle = kernel32.CreateMutexW(None, False, name)
    last_error = kernel32.GetLastError()
    if last_error == _ERROR_ALREADY_EXISTS:
        # Duplicate handle to an existing mutex — close it so we don't leak.
        if handle:
            kernel32.CloseHandle(handle)
        return InstanceLock(acquired=False, handle=None)
    return InstanceLock(acquired=True, handle=handle)


def focus_existing_window(title: str) -> bool:
    """Best-effort: find the existing WIA window by title and bring it
    to the foreground. Returns ``True`` on success, ``False`` otherwise.

    Used by the second-instance branch so a double-click on the shortcut
    feels like a focus instead of a silent no-op.
    """
    if not sys.platform.startswith("win"):
        return False

    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    # Restore if minimized, then raise to foreground.
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    return bool(user32.SetForegroundWindow(hwnd))
