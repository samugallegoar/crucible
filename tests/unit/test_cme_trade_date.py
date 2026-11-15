"""CME Globex trade date from a bar's open: Chicago wall clock + 7 h (ADR-0087).

Expected dates are worked out by hand from the CME schedule (session opens 17:00 Chicago the
evening before and the trade date changes at 17:00 Chicago), not derived from the code."""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from crucible.data.calendars import cme_trade_date_expr
from crucible.data.continuous import trade_date_expr

_NS = 1_000_000_000


def _ns(text: str) -> int:
    parsed = dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC)
    return int(parsed.timestamp()) * _NS


def _trade_date(open_utc: str) -> dt.date:
    frame = pl.DataFrame({"opened": [_ns(open_utc)]})
    return frame.select(cme_trade_date_expr(pl.col("opened")).alias("d"))["d"][0]


@pytest.mark.parametrize(
    ("open_utc", "expected"),
    [
        # winter (CST = UTC-6): 16:00-16:14 Chicago on a Friday are still Friday's session. The
        # 2012-12..2015-03 Friday close was 16:15 CT; a fixed +2 h UTC sent these to Saturday.
        ("2013-01-11T22:00:00", dt.date(2013, 1, 11)),
        ("2013-01-11T22:14:00", dt.date(2013, 1, 11)),
        # winter Sunday reopen at 17:00 CST = 23:00 UTC belongs to Monday; the break before it
        # (22:59 UTC) still belongs to Sunday's (empty) date
        ("2013-01-13T23:00:00", dt.date(2013, 1, 14)),
        ("2013-01-13T22:59:00", dt.date(2013, 1, 13)),
        # summer (CDT = UTC-5): reopen 17:00 CDT = 22:00 UTC; last Friday minute 16:59 CDT
        ("2013-07-14T22:00:00", dt.date(2013, 7, 15)),
        ("2013-07-12T21:59:00", dt.date(2013, 7, 12)),
        # DST spring forward (Sunday 2013-03-10, 02:00 -> 03:00 Chicago): the evening reopen
        # is already in CDT
        ("2013-03-10T22:00:00", dt.date(2013, 3, 11)),
        # DST fall back (Sunday 2013-11-03): the evening reopen is in CST
        ("2013-11-03T23:00:00", dt.date(2013, 11, 4)),
        # an ordinary mid-session minute and the first minute after the reopen
        ("2013-01-15T15:00:00", dt.date(2013, 1, 15)),
        ("2013-01-15T23:00:00", dt.date(2013, 1, 16)),
    ],
)
def test_trade_date_by_hand(open_utc: str, expected: dt.date) -> None:
    assert _trade_date(open_utc) == expected


def test_every_trading_minute_of_a_winter_friday_is_fridays_date() -> None:
    """Friday 2013-01-11 trades until 16:15 CST (22:15 UTC): every bar opening from 21:00 to
    22:14 UTC is Friday's, none is a Saturday (the market is closed all weekend, so a Saturday
    date can only come from a mis-assigned bar)."""
    start = _ns("2013-01-11T21:00:00")
    stop = _ns("2013-01-11T22:14:00")
    opens = list(range(start, stop + 1, 60 * _NS))
    dates = (
        pl.DataFrame({"opened": opens})
        .select(cme_trade_date_expr(pl.col("opened")).alias("d"))["d"]
        .unique()
        .to_list()
    )
    assert dates == [dt.date(2013, 1, 11)]


def test_continuous_builder_uses_the_bar_open_not_the_close() -> None:
    """``trade_date_expr`` takes the CLOSE ``event_time``: a 1-minute bar closing at 23:00 UTC
    (winter) opened at 22:59 UTC and still belongs to the date before the reopen."""
    closes = [_ns("2013-01-13T23:00:00"), _ns("2013-01-13T23:01:00")]
    out = pl.DataFrame({"event_time": closes}).select(trade_date_expr(60).alias("d"))["d"].to_list()
    assert out == [dt.date(2013, 1, 13), dt.date(2013, 1, 14)]
