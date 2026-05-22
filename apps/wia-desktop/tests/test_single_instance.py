"""Tests for single-instance enforcement."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from wia import single_instance


def _install_fake_windll(
    monkeypatch: pytest.MonkeyPatch,
    kernel32: MagicMock,
    user32: MagicMock | None = None,
) -> None:
    """Pretend we're on Windows with a stub ``ctypes.windll``."""
    import ctypes

    fake_windll = types.SimpleNamespace(
        kernel32=kernel32,
        user32=user32 or MagicMock(),
    )
    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setattr(ctypes, "windll", fake_windll, raising=False)


def test_acquire_returns_acquired_on_first_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel32 = MagicMock()
    kernel32.CreateMutexW.return_value = 0xCAFE
    kernel32.GetLastError.return_value = 0  # ERROR_SUCCESS
    _install_fake_windll(monkeypatch, kernel32)

    lock = single_instance.acquire("Global\\test-mutex")

    assert lock.acquired is True
    assert lock.handle == 0xCAFE
    kernel32.CreateMutexW.assert_called_once_with(None, False, "Global\\test-mutex")
    kernel32.CloseHandle.assert_not_called()


def test_acquire_returns_not_acquired_when_already_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel32 = MagicMock()
    kernel32.CreateMutexW.return_value = 0xBEEF
    kernel32.GetLastError.return_value = 183  # ERROR_ALREADY_EXISTS
    _install_fake_windll(monkeypatch, kernel32)

    lock = single_instance.acquire()

    assert lock.acquired is False
    assert lock.handle is None
    # Duplicate handle must be closed so we don't leak.
    kernel32.CloseHandle.assert_called_once_with(0xBEEF)


def test_acquire_uses_default_mutex_name(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel32 = MagicMock()
    kernel32.CreateMutexW.return_value = 0x1
    kernel32.GetLastError.return_value = 0
    _install_fake_windll(monkeypatch, kernel32)

    single_instance.acquire()

    kernel32.CreateMutexW.assert_called_once_with(None, False, single_instance.MUTEX_NAME)


def test_acquire_is_noop_on_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)

    lock = single_instance.acquire()

    assert lock.acquired is True
    assert lock.handle is None


def test_focus_existing_window_restores_and_foregrounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user32 = MagicMock()
    user32.FindWindowW.return_value = 0x1234
    user32.IsIconic.return_value = 1
    user32.SetForegroundWindow.return_value = 1
    _install_fake_windll(monkeypatch, MagicMock(), user32=user32)

    assert single_instance.focus_existing_window("WIA — Work Intelligence Agent") is True

    user32.FindWindowW.assert_called_once_with(None, "WIA — Work Intelligence Agent")
    user32.ShowWindow.assert_called_once_with(0x1234, 9)  # SW_RESTORE
    user32.SetForegroundWindow.assert_called_once_with(0x1234)


def test_focus_existing_window_returns_false_when_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user32 = MagicMock()
    user32.FindWindowW.return_value = 0  # no window
    _install_fake_windll(monkeypatch, MagicMock(), user32=user32)

    assert single_instance.focus_existing_window("nope") is False
    user32.ShowWindow.assert_not_called()
    user32.SetForegroundWindow.assert_not_called()


def test_focus_existing_window_skips_restore_when_not_iconic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user32 = MagicMock()
    user32.FindWindowW.return_value = 0x999
    user32.IsIconic.return_value = 0
    user32.SetForegroundWindow.return_value = 1
    _install_fake_windll(monkeypatch, MagicMock(), user32=user32)

    assert single_instance.focus_existing_window("WIA") is True
    user32.ShowWindow.assert_not_called()
    user32.SetForegroundWindow.assert_called_once_with(0x999)


def test_focus_existing_window_is_noop_on_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux", raising=False)

    assert single_instance.focus_existing_window("WIA") is False
