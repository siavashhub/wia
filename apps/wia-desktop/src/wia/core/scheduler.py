"""Background scan scheduler.

Periodically rebuilds the briefing for the current week. The interval is
persisted in the ``user_pref`` table under ``schedule_interval_minutes``;
a value of ``0`` disables the schedule (manual refresh only).
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from datetime import UTC, datetime

from wia.core.orchestrator import build_briefing
from wia.core.types import Briefing
from wia.core.week import week_bounds
from wia.storage import prefs, scan_history

log = logging.getLogger(__name__)

PREF_INTERVAL = "schedule_interval_minutes"
# Legacy "last scan" prefs — kept for backward compat; the scan_history table
# is now the source of truth.
PREF_LAST_SCAN = "last_scan_at"
PREF_LAST_STATUS = "last_scan_status"
PREF_LAST_WEEK = "last_scan_week_of"
PREF_LAST_TRIGGER = "last_scan_trigger"

# Allowed intervals in minutes. ``0`` means "disabled / manual only".
ALLOWED_INTERVALS = [0, 60, 120, 240, 480, 1440]
DEFAULT_INTERVAL = 0


class Scheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stop = False

    @property
    def interval_minutes(self) -> int:
        raw = prefs.get_pref(PREF_INTERVAL)
        try:
            v = int(raw) if raw is not None else DEFAULT_INTERVAL
        except ValueError:
            v = DEFAULT_INTERVAL
        return v if v in ALLOWED_INTERVALS else DEFAULT_INTERVAL

    def set_interval(self, minutes: int) -> int:
        if minutes not in ALLOWED_INTERVALS:
            raise ValueError(f"interval must be one of {ALLOWED_INTERVALS}")
        prefs.set_pref(PREF_INTERVAL, str(minutes))
        self._wake.set()
        return minutes

    @property
    def last_scan_at(self) -> datetime | None:
        raw = prefs.get_pref(PREF_LAST_SCAN)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    @property
    def last_scan_status(self) -> str | None:
        return prefs.get_pref(PREF_LAST_STATUS)

    @property
    def last_scan_week_of(self) -> str | None:
        return prefs.get_pref(PREF_LAST_WEEK)

    @property
    def last_scan_trigger(self) -> str | None:
        return prefs.get_pref(PREF_LAST_TRIGGER)

    def record_scan(
        self,
        status: str,
        *,
        week_of: str,
        trigger: str = "manual",
        entry_count: int = 0,
        duration_ms: int = 0,
    ) -> None:
        """Persist a scan attempt: updates the "last scan" prefs and appends
        a row to ``scan_history``. ``week_of`` is the ISO Monday of the
        scanned week so the UI can show *which* week the scan covered."""
        now = datetime.now(UTC)
        prefs.set_pref(PREF_LAST_SCAN, now.isoformat())
        prefs.set_pref(PREF_LAST_STATUS, status)
        prefs.set_pref(PREF_LAST_WEEK, week_of)
        prefs.set_pref(PREF_LAST_TRIGGER, trigger)
        scan_history.record(
            ran_at=now,
            week_of=week_of,
            trigger=trigger,
            status=status,
            entry_count=entry_count,
            duration_ms=duration_ms,
        )

    async def run_once(self) -> str:
        """Run a scheduled scan over the *current* week and persist history."""
        monday, _sunday = week_bounds()
        week_iso = monday.isoformat()
        started = time.perf_counter()
        entry_count = 0
        try:
            briefing: Briefing = await build_briefing(refresh=True)
            status = briefing.status
            entry_count = len(briefing.entries)
        except Exception as exc:
            log.exception("Scheduled scan failed")
            status = f"error: {exc.__class__.__name__}"
        duration_ms = int((time.perf_counter() - started) * 1000)
        self.record_scan(
            status,
            week_of=week_iso,
            trigger="scheduled",
            entry_count=entry_count,
            duration_ms=duration_ms,
        )
        return status

    async def _loop(self) -> None:
        log.info("Scheduler loop started")
        while not self._stop:
            interval = self.interval_minutes
            if interval <= 0:
                # Disabled; wait until interval changes.
                self._wake.clear()
                try:
                    await self._wake.wait()
                except asyncio.CancelledError:
                    break
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval * 60)
                # Woken up early (interval change or manual trigger).
                self._wake.clear()
                continue
            except TimeoutError:
                pass
            log.info("Scheduled scan firing (interval=%d min)", interval)
            await self.run_once()

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = False
        loop = loop or asyncio.get_event_loop()
        self._task = loop.create_task(self._loop())

    async def stop(self) -> None:
        self._stop = True
        self._wake.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None


_scheduler = Scheduler()


def get_scheduler() -> Scheduler:
    return _scheduler
