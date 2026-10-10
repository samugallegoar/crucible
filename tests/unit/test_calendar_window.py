"""Exchange calendars are built over a window derived from the run, never from today (ADR-0053).

exchange_calendars' default window is "today minus 20 years to today plus one year", so the same
config behaved differently on different dates. The window here is the requested range padded by
366 days each side, so it depends only on the config or data.
"""

from __future__ import annotations

import datetime as dt

import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import TimestampNs, to_timestamp_ns
from crucible.data.calendars import ExchangeCalendarAdapter, get_trading_calendar


def _ns(year: int, month: int, day: int, hour: int = 0) -> TimestampNs:
    return to_timestamp_ns(dt.datetime(year, month, day, hour, tzinfo=dt.UTC))


def test_the_window_is_the_requested_range_padded_by_366_days() -> None:
    cal = ExchangeCalendarAdapter("XNYS", start=_ns(2005, 6, 1), end=_ns(2005, 12, 31))
    assert cal.window == (dt.date(2004, 5, 31), dt.date(2007, 1, 1))


def test_sessions_older_than_todays_default_window_are_available() -> None:
    """The default window starts around 2006; 2005-01-03 is a real XNYS session
    (close 16:00 EST = 21:00 UTC)."""
    cal = get_trading_calendar("XNYS", start=_ns(2005, 1, 1), end=_ns(2005, 1, 10))
    assert cal.session_closes(_ns(2005, 1, 1), _ns(2005, 1, 10))[0] == _ns(2005, 1, 3, 21)


def test_a_window_is_required_for_an_exchange_calendar() -> None:
    with pytest.raises(TypeError):
        get_trading_calendar("XNYS")  # type: ignore[call-arg]


def test_the_24_7_calendar_ignores_the_window() -> None:
    cal = get_trading_calendar("24/7", start=_ns(2020, 1, 1), end=_ns(2020, 1, 2))
    assert cal.name == "24/7"


def test_an_unknown_calendar_is_refused_with_a_message() -> None:
    with pytest.raises(ConfigurationError, match="cannot cover"):
        ExchangeCalendarAdapter("NOPE", start=_ns(2020, 1, 1), end=_ns(2020, 2, 1))


def test_end_before_start_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="end"):
        ExchangeCalendarAdapter("XNYS", start=_ns(2020, 2, 1), end=_ns(2020, 1, 1))
