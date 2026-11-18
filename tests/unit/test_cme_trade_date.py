"""CME Globex trade dates of bars from the session calendar (ADR-0091, ADR-0092).

Expected dates are worked out by hand from the CME schedules transcribed in the table (the
session of trade date D opens the evening before; 15:30 Chicago before 2012-11-19, 17:00 after),
not derived from the code. ``trade_dates`` takes the bar's CLOSE ``event_time``."""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from crucible.data.cme_sessions import session_trade_dates
from crucible.data.continuous import calendar_for, outside_calendar, trade_dates

_NS = 1_000_000_000


def _ns(text: str) -> int:
    parsed = dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC)
    return int(parsed.timestamp()) * _NS


def _trade_date(open_utc: str, root: str = "ES") -> dt.date:
    closes = pl.Series("event_time", [_ns(open_utc) + 60 * _NS])
    return trade_dates(closes, calendar_for(root), 60)[0]  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    ("open_utc", "expected"),
    [
        # winter (CST = UTC-6): 16:00-16:14 Chicago on a Friday are still Friday's session (the
        # 2012-11..2015-09 close was 16:15 CT); the print in the minute after it stays Friday's
        ("2013-01-11T22:00:00", dt.date(2013, 1, 11)),
        ("2013-01-11T22:14:00", dt.date(2013, 1, 11)),
        ("2013-01-11T22:15:00", dt.date(2013, 1, 11)),
        # winter Sunday reopen at 17:00 CST = 23:00 UTC belongs to Monday; a print before it
        # (22:59 UTC) belongs to the last session that opened, Friday's (never a Sunday date)
        ("2013-01-13T23:00:00", dt.date(2013, 1, 14)),
        ("2013-01-13T22:59:00", dt.date(2013, 1, 11)),
        # summer (CDT = UTC-5): reopen 17:00 CDT = 22:00 UTC
        ("2013-07-14T22:00:00", dt.date(2013, 7, 15)),
        # DST spring forward (Sunday 2013-03-10): the evening reopen is already in CDT
        ("2013-03-10T22:00:00", dt.date(2013, 3, 11)),
        # DST fall back (Sunday 2013-11-03): the evening reopen is in CST
        ("2013-11-03T23:00:00", dt.date(2013, 11, 4)),
        # an ordinary mid-session minute and the first minute after the weekday reopen
        ("2013-01-15T15:00:00", dt.date(2013, 1, 15)),
        ("2013-01-15T23:00:00", dt.date(2013, 1, 16)),
    ],
)
def test_trade_date_by_hand(open_utc: str, expected: dt.date) -> None:
    assert _trade_date(open_utc) == expected


@pytest.mark.parametrize(
    ("open_utc", "expected"),
    [
        # Tuesday 2011-03-15 (CDT): the session closed 15:15 and the next opened 15:30 Chicago
        # (20:30 UTC). The 17:00 rule of ADR-0087 gave 15:30-17:00 to the same date: wrong.
        ("2011-03-15T20:14:00", dt.date(2011, 3, 15)),
        ("2011-03-15T20:30:00", dt.date(2011, 3, 16)),
        ("2011-03-15T20:45:00", dt.date(2011, 3, 16)),
        ("2011-03-15T21:29:00", dt.date(2011, 3, 16)),
        # the 16:30-17:00 maintenance window is off schedule; its prints stay with the session
        # that opened at 15:30
        ("2011-03-15T21:40:00", dt.date(2011, 3, 16)),
        ("2011-03-15T22:00:00", dt.date(2011, 3, 16)),
    ],
)
def test_before_2012_11_19_the_trade_date_changes_at_1530(open_utc: str, expected: dt.date) -> None:
    assert _trade_date(open_utc) == expected


def test_friday_booked_to_monday_takes_mondays_trade_date() -> None:
    """2020 Independence Day: Friday 2020-07-03 is no trade date; Monday 07-06's session opens
    Thursday 07-02 17:00 CDT and halts Friday 12:00 to Sunday 17:00. A Friday 10:00 CDT bar is
    therefore Monday's (the 17:00 rule gave it Friday 07-03, a date with no session)."""
    assert _trade_date("2020-07-03T15:00:00") == dt.date(2020, 7, 6)
    assert _trade_date("2020-07-02T22:00:00") == dt.date(2020, 7, 6)


def test_order_is_kept_and_duplicates_share_a_date() -> None:
    closes = pl.Series(
        "event_time",
        [_ns("2013-01-15T23:01:00"), _ns("2013-01-15T15:01:00"), _ns("2013-01-15T23:01:00")],
    )
    got = trade_dates(closes, calendar_for("ES"), 60).to_list()
    assert got == [dt.date(2013, 1, 16), dt.date(2013, 1, 15), dt.date(2013, 1, 16)]


def test_off_schedule_flag() -> None:
    ends = pl.Series([_ns("2013-01-11T22:15:00"), _ns("2013-01-11T22:16:00")]).to_numpy()
    _, on = session_trade_dates(calendar_for("ES"), ends, 60)
    assert on.tolist() == [True, False]  # the bar 16:14-16:15 is in; 16:15-16:16 is a print


def test_outside_coverage() -> None:
    """NKD is covered from trade date 2012-11-19 (its session opens 2012-11-18 17:00 CST)."""
    closes = pl.Series([_ns("2012-11-16T15:01:00"), _ns("2012-11-18T23:01:00")])
    assert outside_calendar(closes, calendar_for("NKD"), 60).to_list() == [True, False]
