"""session_open_at: the open of the session containing a timestamp (ADR-0046)."""

from __future__ import annotations

import datetime as dt

from crucible.core.types import TimestampNs
from crucible.data.calendars import AlwaysOpenCalendar, get_trading_calendar

DAY = 86_400 * 10**9


def _ns(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    stamp = dt.datetime(year, month, day, hour, minute, tzinfo=dt.UTC)
    return int(stamp.timestamp() * 10**9)


def test_a_24_7_session_is_the_utc_day_and_midnight_starts_it() -> None:
    """A timestamp exactly at midnight is the start of that day (the same reading as
    a midnight-stamped ex-date on an exchange calendar)."""
    calendar = AlwaysOpenCalendar()
    assert calendar.session_open_at(TimestampNs(3 * DAY)) == 3 * DAY
    assert calendar.session_open_at(TimestampNs(2 * DAY + 5)) == 2 * DAY
    assert calendar.session_open_at(TimestampNs(3 * DAY - 1)) == 2 * DAY


def test_an_exchange_session_open_is_found_inside_and_none_outside() -> None:
    """XNYS Thursday 2020-01-02 trades 14:30-21:00 UTC; Saturday 2020-01-04 is closed."""
    calendar = get_trading_calendar(
        "XNYS", start=TimestampNs(_ns(2020, 1, 1, 0)), end=TimestampNs(_ns(2020, 1, 10, 0))
    )
    open_ns = _ns(2020, 1, 2, 14, 30)
    assert calendar.session_open_at(TimestampNs(_ns(2020, 1, 2, 15))) == open_ns
    assert calendar.session_open_at(TimestampNs(_ns(2020, 1, 2, 21))) == open_ns  # at the close
    assert calendar.session_open_at(TimestampNs(_ns(2020, 1, 2, 10))) is None  # before the open
    assert calendar.session_open_at(TimestampNs(_ns(2020, 1, 4, 15))) is None  # weekend
