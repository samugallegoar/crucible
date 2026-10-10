"""Calendars (XNYS + 24/7) and universe membership incl. delisting boundary."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from crucible.core.types import Symbol, TimestampNs, to_timestamp_ns
from crucible.data.calendars import AlwaysOpenCalendar, get_trading_calendar
from crucible.data.contracts import END_AT_OPEN
from crucible.data.universe import TableUniverseProvider

DAY = 86_400 * 10**9


def test_xnys_first_week_of_2020_has_three_sessions() -> None:
    start = to_timestamp_ns(datetime(2020, 1, 1, tzinfo=UTC))
    end = to_timestamp_ns(datetime(2020, 1, 5, tzinfo=UTC))
    cal = get_trading_calendar("XNYS", start=start, end=end)
    closes = cal.session_closes(start, end)
    # Jan 1 is a holiday; Jan 2 and Jan 3 are sessions; Jan 4-5 weekend.
    assert len(closes) == 2
    # NYSE closes 16:00 America/New_York = 21:00 UTC in January.
    assert closes[0] == to_timestamp_ns(datetime(2020, 1, 2, 21, 0, tzinfo=UTC))


def test_always_open_calendar_daily_closes() -> None:
    cal = AlwaysOpenCalendar()
    closes = cal.session_closes(TimestampNs(0), TimestampNs(3 * DAY))
    assert closes == [0, DAY, 2 * DAY, 3 * DAY]
    assert cal.is_open(TimestampNs(12345)) is True
    assert cal.next_session_close(TimestampNs(1)) == DAY


def test_universe_membership_and_delisting() -> None:
    table = pl.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "start_at": [0, 0],
            "end_at": [END_AT_OPEN, 5 * DAY],  # BBB delists at day 5
            "reason": ["initial", "initial"],
            "event_time": [0, 0],
            "available_at": [0, 0],
        }
    )
    universe = TableUniverseProvider(table)
    assert universe.members(TimestampNs(DAY)) == {Symbol("AAA"), Symbol("BBB")}
    # end_at is exclusive: at the delisting instant BBB is out
    assert universe.members(TimestampNs(5 * DAY)) == {Symbol("AAA")}
    assert universe.all_symbols() == {Symbol("AAA"), Symbol("BBB")}
