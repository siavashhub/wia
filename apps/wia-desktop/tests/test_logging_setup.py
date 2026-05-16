"""Tests for the logging setup module."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from wia.config import Settings
from wia.logging_setup import (
    _CONFIGURED_MARKER,
    LOG_FILENAME,
    configure_logging,
    current_log_path,
)


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Snapshot + restore root handlers around each test."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for h in list(root.handlers):
        if getattr(h, _CONFIGURED_MARKER, False):
            root.removeHandler(h)
            h.close()
    # Reinstate originals.
    for h in saved_handlers:
        if h not in root.handlers:
            root.addHandler(h)
    root.setLevel(saved_level)


def _make_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides) -> Settings:
    monkeypatch.setenv("WIA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WIA_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("WIA_LOG_LEVEL", str(overrides.pop("log_level", "DEBUG")))
    monkeypatch.setenv("WIA_LOG_TO_FILE", "1" if overrides.pop("log_to_file", True) else "0")
    monkeypatch.setenv("WIA_LOG_RETENTION_DAYS", str(overrides.pop("log_retention_days", 30)))
    assert not overrides, f"unexpected overrides: {overrides}"
    return Settings()


def test_configure_logging_creates_rotating_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _make_settings(tmp_path, monkeypatch)
    configure_logging(settings)
    logging.getLogger("wia.test").info("hello world")

    log_file = tmp_path / "logs" / LOG_FILENAME
    assert log_file.exists()
    contents = log_file.read_text(encoding="utf-8")
    assert "hello world" in contents
    assert "INFO" in contents


def test_configure_logging_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _make_settings(tmp_path, monkeypatch)
    configure_logging(settings)
    configure_logging(settings)
    configure_logging(settings)

    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, _CONFIGURED_MARKER, False)]
    # Exactly one stream + one file handler each pass.
    assert len(ours) == 2


def test_configure_logging_respects_log_to_file_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _make_settings(tmp_path, monkeypatch, log_to_file=False)
    configure_logging(settings)

    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, _CONFIGURED_MARKER, False)]
    assert len(ours) == 1  # console only
    assert isinstance(ours[0], logging.StreamHandler)
    assert current_log_path(settings) is None


def test_configure_logging_honors_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _make_settings(tmp_path, monkeypatch, log_level="WARNING")
    configure_logging(settings)
    logging.getLogger("wia.test").debug("debug-msg")
    logging.getLogger("wia.test").warning("warn-msg")

    log_file = tmp_path / "logs" / LOG_FILENAME
    contents = log_file.read_text(encoding="utf-8")
    assert "warn-msg" in contents
    assert "debug-msg" not in contents


def test_current_log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _make_settings(tmp_path, monkeypatch)
    assert current_log_path(settings) == str(tmp_path / "logs" / LOG_FILENAME)
