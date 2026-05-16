"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from wia import __version__
from wia.config import get_settings
from wia.logging_setup import current_log_path

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/health/logs")
async def logs_info() -> dict[str, object]:
    """Return information about the on-disk log file.

    Used by the UI's "Open log folder" action so support can ask users for
    logs without having to remember the OS-specific path.
    """
    settings = get_settings()
    path = current_log_path(settings)
    return {
        "enabled": settings.log_to_file,
        "level": settings.log_level,
        "retention_days": settings.log_retention_days,
        "log_dir": str(settings.log_dir),
        "log_file": path,
    }
