"""Update-check logic for WIA.

Queries the GitHub Releases API for the latest release of the WIA repo,
compares it against the running ``__version__``, and caches the result
in memory for ``CACHE_TTL_SECONDS`` so the UI can call the check endpoint
on every page load without hammering the GitHub API.

No authentication is needed — the siavashhub/wia repo is public.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from wia import __version__

log = logging.getLogger(__name__)

_RELEASES_URL = "https://api.github.com/repos/siavashhub/wia/releases/latest"
# Cache TTL: 4 hours
CACHE_TTL_SECONDS = 4 * 60 * 60
# Request timeout — short so a hung network doesn't block the UI call.
_REQUEST_TIMEOUT = 8.0

_TAG_RE = re.compile(r"^v?(\d+\.\d+\.\d+)")


def _parse_semver(tag: str) -> tuple[int, int, int] | None:
    """Extract (major, minor, patch) from a version tag like ``v1.2.3``.

    Returns ``None`` for tags that don't match the expected pattern so
    pre-release / rc tags are treated as unknown rather than crashing.
    """
    m = _TAG_RE.match(tag.strip())
    if not m:
        return None
    try:
        parts = tuple(int(x) for x in m.group(1).split("."))
        if len(parts) == 3:
            return parts  # type: ignore[return-value]
    except ValueError:
        pass
    return None


@dataclass
class UpdateInfo:
    """Snapshot of the latest-release check."""

    current_version: str
    latest_version: str | None
    update_available: bool
    release_url: str | None
    checked_at: float = field(default_factory=time.monotonic)

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.checked_at) > CACHE_TTL_SECONDS


# Module-level in-memory cache. A single desktop process only ever has
# one instance, so a plain module variable is sufficient.
_cache: UpdateInfo | None = None


async def check_for_updates(*, force: bool = False) -> UpdateInfo:
    """Return update information, using the in-memory cache unless stale.

    Set ``force=True`` to bypass the cache (e.g. user clicked "Check now").
    Errors from the GitHub API are swallowed and result in an ``UpdateInfo``
    with ``latest_version=None`` so the UI degrades gracefully.
    """
    global _cache

    if not force and _cache is not None and not _cache.expired:
        return _cache

    result = await _fetch_update_info()
    _cache = result
    return result


async def _fetch_update_info() -> UpdateInfo:
    current = __version__
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(
                _RELEASES_URL,
                headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        log.debug("Update check failed", exc_info=True)
        return UpdateInfo(
            current_version=current,
            latest_version=None,
            update_available=False,
            release_url=None,
        )

    tag: str = data.get("tag_name", "")
    html_url: str | None = data.get("html_url") or None

    current_parsed = _parse_semver(current)
    latest_parsed = _parse_semver(tag)

    if current_parsed is None or latest_parsed is None:
        update_available = False
    else:
        update_available = latest_parsed > current_parsed

    latest_version = tag.lstrip("v") if tag else None

    log.debug(
        "Update check: current=%s latest=%s update_available=%s",
        current,
        latest_version,
        update_available,
    )

    return UpdateInfo(
        current_version=current,
        latest_version=latest_version,
        update_available=update_available,
        release_url=html_url,
    )
