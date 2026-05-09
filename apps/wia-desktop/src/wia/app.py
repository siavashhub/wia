"""FastAPI application factory."""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from wia.api import briefing, entries, export, health, prefs, review, schedule, workiq
from wia.config import get_settings
from wia.core.scheduler import get_scheduler
from wia.storage.db import init_db

log = logging.getLogger(__name__)

UI_DIR = Path(__file__).parent / "ui"
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
_ASSET_RE = re.compile(r"(/static/[A-Za-z0-9_./-]+\.(?:css|js|png))")


def _render_index() -> str:
    """Read index.html and append a per-file mtime cache buster to local assets.

    WebView2 caches static responses aggressively; without a query-string
    version the user can keep seeing stale CSS/JS after an upgrade.
    """
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")

    def _bust(match: re.Match[str]) -> str:
        url = match.group(1)
        rel = url[len("/static/") :]
        path = UI_DIR / rel
        try:
            ver = int(path.stat().st_mtime)
        except OSError:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}v={ver}"

    return _ASSET_RE.sub(_bust, html)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    log.info("WIA starting; data dir = %s", settings.data_dir)
    init_db()
    sched = get_scheduler()
    sched.start()
    yield
    await sched.stop()
    log.info("WIA shutting down")


def create_app() -> FastAPI:
    app = FastAPI(title="WIA", version="0.1.0", lifespan=lifespan)

    app.include_router(health.router, prefix="/api")
    app.include_router(workiq.router, prefix="/api/workiq", tags=["workiq"])
    app.include_router(briefing.router, prefix="/api/briefing", tags=["briefing"])
    app.include_router(entries.router, prefix="/api/entries", tags=["entries"])
    app.include_router(export.router, prefix="/api/export", tags=["export"])
    app.include_router(schedule.router, prefix="/api/schedule", tags=["schedule"])
    app.include_router(prefs.router, prefix="/api/prefs", tags=["prefs"])
    app.include_router(review.router, prefix="/api/review", tags=["review"])

    if UI_DIR.exists():
        app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> HTMLResponse:
            return HTMLResponse(_render_index(), headers=_NO_STORE)

    return app
