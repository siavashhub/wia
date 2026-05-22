"""Update-check API endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from wia.core.updates import check_for_updates

router = APIRouter()


class UpdateStatus(BaseModel):
    current_version: str
    latest_version: str | None
    update_available: bool
    release_url: str | None


@router.get("/check")
async def get_update_check(
    force: bool = Query(default=False, description="Bypass the in-memory cache"),
) -> UpdateStatus:
    """Return the latest-release info from GitHub.

    The result is cached for 4 hours so this endpoint is safe to call on
    every page load.  Pass ``?force=true`` to bypass the cache.
    """
    info = await check_for_updates(force=force)
    return UpdateStatus(
        current_version=info.current_version,
        latest_version=info.latest_version,
        update_available=info.update_available,
        release_url=info.release_url,
    )
