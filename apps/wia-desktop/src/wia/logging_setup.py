"""Application-wide logging configuration.

WIA is shipped as a windowed pywebview app; in packaged builds there is no
attached console, so anything written to ``stderr`` is effectively lost. To
make user-side troubleshooting possible we mirror log records to a daily
rotating file under ``data_dir/logs/wia.log`` with 30-day retention by
default.

Rotation uses :class:`~logging.handlers.TimedRotatingFileHandler` so retention
is enforced by ``backupCount`` — no separate cleanup job needed.
"""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wia.config import Settings

LOG_FILENAME = "wia.log"
_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_CONFIGURED_MARKER = "_wia_configured"


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure the root logger with console + rotating file handlers.

    Idempotent: re-entry (e.g. under PyInstaller, or repeated lifespan
    startups in tests) clears previously-installed handlers tagged by this
    module before reattaching.
    """
    root = logging.getLogger()
    level = _coerce_level(settings.log_level)
    root.setLevel(level)

    # Remove handlers we previously installed so reconfiguration doesn't
    # double-log. Leave foreign handlers (e.g. pytest's caplog) alone.
    for handler in list(root.handlers):
        if getattr(handler, _CONFIGURED_MARKER, False):
            root.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    setattr(console, _CONFIGURED_MARKER, True)
    root.addHandler(console)

    if settings.log_to_file:
        try:
            log_path = settings.log_dir / LOG_FILENAME
            file_handler = TimedRotatingFileHandler(
                log_path,
                when="midnight",
                backupCount=max(0, settings.log_retention_days),
                encoding="utf-8",
                delay=True,
                utc=False,
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            setattr(file_handler, _CONFIGURED_MARKER, True)
            root.addHandler(file_handler)
        except OSError as exc:
            # Never let logging take down app startup — fall back to
            # console-only and record the failure once.
            logging.getLogger(__name__).warning(
                "File logging disabled (%s): %s", type(exc).__name__, exc
            )

    return root


def _coerce_level(value: str | int) -> int:
    if isinstance(value, int):
        return value
    name = str(value).strip().upper() or "INFO"
    resolved = logging.getLevelName(name)
    return resolved if isinstance(resolved, int) else logging.INFO


def current_log_path(settings: Settings) -> str | None:
    """Return the active log file path, or ``None`` if file logging is off."""
    if not settings.log_to_file:
        return None
    return str(settings.log_dir / LOG_FILENAME)
