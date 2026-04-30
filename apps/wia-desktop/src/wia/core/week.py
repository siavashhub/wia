"""Week-range helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta


def week_bounds(any_day: date | None = None) -> tuple[date, date]:
    """Return (Monday, Sunday) of the week containing ``any_day``.

    The end of the week is Sunday so the briefing covers the full
    seven-day calendar (including weekend events). Defaults to today.
    """
    if any_day is None:
        any_day = date.today()
    monday = any_day - timedelta(days=any_day.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def week_days(monday: date, tzinfo=None) -> list[datetime]:
    """Return seven datetimes (Mon..Sun at 00:00) in ``tzinfo``.

    Defaults to the system local timezone so that gap-filling and the
    work-day window line up with the user's calendar (M365 returns events
    with the user's offset, e.g. ``-04:00``).
    """
    if tzinfo is None:
        tzinfo = datetime.now().astimezone().tzinfo
    return [
        datetime.combine(monday + timedelta(days=i), time(0, 0), tzinfo=tzinfo) for i in range(7)
    ]
