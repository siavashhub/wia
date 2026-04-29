from datetime import date

from wia.core.week import week_bounds, week_days


def test_week_bounds_for_a_wednesday():
    monday, sunday = week_bounds(date(2026, 4, 22))  # Wednesday
    assert monday == date(2026, 4, 20)
    assert sunday == date(2026, 4, 26)


def test_week_days_returns_seven_days():
    monday, _ = week_bounds(date(2026, 4, 22))
    days = week_days(monday)
    assert len(days) == 7
    assert days[0].date() == date(2026, 4, 20)
    assert days[6].date() == date(2026, 4, 26)
