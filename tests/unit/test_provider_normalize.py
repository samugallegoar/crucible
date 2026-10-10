"""Provider-neutral raw bars become ``BAR_SCHEMA`` bars (ADR-0063).

Hand-computed UTC nanoseconds (seconds since the epoch times 10**9):

* 2024-01-02 (Tue) NYSE closes 16:00 EST = 21:00Z -> 1704229200
* 2024-07-01 (Mon) NYSE closes 16:00 EDT = 20:00Z -> 1719864000 (daylight saving: an hour earlier)
* 2024-11-29 (Fri, day after Thanksgiving) early close 13:00 EST = 18:00Z -> 1732903200
* 24/7 daily bar of 2024-01-02: opens 00:00Z, closes 2024-01-03T00:00Z -> 1704240000
* intraday 5m bar starting 2024-01-02T14:30Z closes 14:35Z -> 1704206100
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from crucible.data.contracts import BAR_SCHEMA
from crucible.data.providers.errors import EmptyDataError, ProviderError
from crucible.data.providers.normalize import normalize_raw, parse_interval

NS = 10**9


def _daily(rows: list[tuple[dt.date, float, float, float, float, float | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [r[0] for r in rows],
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [r[5] for r in rows],
        },
        schema={
            "ts": pl.Date,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )


def test_daily_bars_of_an_exchange_calendar_close_at_the_session_close() -> None:
    raw = _daily(
        [
            (dt.date(2024, 1, 2), 10.0, 11.0, 9.0, 10.5, 100.0),
            (dt.date(2024, 7, 1), 20.0, 21.0, 19.0, 20.5, 200.0),
            (dt.date(2024, 11, 29), 30.0, 31.0, 29.0, 30.5, 300.0),
        ]
    )
    out = normalize_raw(raw, symbol="aapl", interval="1d", calendar="XNYS")
    assert out.frame["event_time"].to_list() == [
        1704229200 * NS,
        1719864000 * NS,
        1732903200 * NS,
    ]
    assert out.frame["symbol"].to_list() == ["AAPL"] * 3
    assert out.frame["available_at"].to_list() == out.frame["event_time"].to_list()
    assert out.dropped == {}


def test_a_24_7_daily_bar_closes_one_day_after_its_open() -> None:
    raw = _daily([(dt.date(2024, 1, 2), 1.0, 2.0, 0.5, 1.5, 10.0)])
    out = normalize_raw(raw, symbol="BTC-USD", interval="1d", calendar="24/7")
    assert out.frame["event_time"].to_list() == [1704240000 * NS]


def test_an_intraday_bar_closes_at_its_start_plus_the_interval() -> None:
    raw = pl.DataFrame(
        {
            "ts": [dt.datetime(2024, 1, 2, 14, 30, tzinfo=dt.UTC)],
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [1.5],
            "volume": [10.0],
        },
        schema={
            "ts": pl.Datetime("us", "UTC"),
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )
    out = normalize_raw(raw, symbol="X", interval="5m", calendar="XNYS")
    assert out.frame["event_time"].to_list() == [1704206100 * NS]


def test_feed_latency_moves_available_at_only() -> None:
    raw = _daily([(dt.date(2024, 1, 2), 10.0, 11.0, 9.0, 10.5, 1.0)])
    out = normalize_raw(raw, symbol="X", interval="1d", calendar="XNYS", feed_latency_s=60)
    assert out.frame["event_time"][0] == 1704229200 * NS
    assert out.frame["available_at"][0] == 1704229200 * NS + 60 * NS


def test_the_output_is_exactly_bar_schema_sorted_and_deduplicated() -> None:
    raw = _daily(
        [
            (dt.date(2024, 1, 3), 11.0, 12.0, 10.0, 11.5, 2.0),
            (dt.date(2024, 1, 2), 10.0, 11.0, 9.0, 10.5, 1.0),
            (dt.date(2024, 1, 3), 11.0, 12.5, 10.0, 12.0, 3.0),  # a later restatement of Jan 3
        ]
    )
    out = normalize_raw(raw, symbol="X", interval="1d", calendar="XNYS")
    assert out.frame.schema == pl.Schema(BAR_SCHEMA)
    assert out.frame["event_time"].is_sorted()
    assert out.frame.height == 2
    assert (
        out.frame.filter(pl.col("event_time") == out.frame["event_time"].max())["close"][0] == 12.0
    )
    assert out.dropped == {"duplicate": 1}


def test_incomplete_rows_and_non_sessions_are_dropped_and_counted() -> None:
    raw = _daily(
        [
            (dt.date(2024, 1, 2), 10.0, 11.0, 9.0, 10.5, 1.0),
            (dt.date(2024, 1, 3), float("nan"), 11.0, 9.0, 10.5, 1.0),  # NaN price
            (dt.date(2024, 1, 6), 10.0, 11.0, 9.0, 10.5, 1.0),  # a Saturday
            (dt.date(2024, 1, 4), 10.0, 11.0, 9.0, 10.5, None),  # no volume: kept, volume 0
        ]
    )
    out = normalize_raw(raw, symbol="X", interval="1d", calendar="XNYS")
    assert out.frame.height == 2
    assert out.dropped == {"incomplete": 1, "not_a_session": 1}
    assert out.frame["volume"].to_list() == [1.0, 0.0]


def test_an_ohlc_violation_is_left_for_the_quality_gate_unless_clamping_is_requested() -> None:
    raw = _daily([(dt.date(2024, 1, 2), 10.0, 10.2, 9.0, 10.5, 1.0)])  # close above high
    kept = normalize_raw(raw, symbol="X", interval="1d", calendar="XNYS")
    assert kept.frame["high"][0] == 10.2
    assert kept.repaired == {}
    fixed = normalize_raw(raw, symbol="X", interval="1d", calendar="XNYS", ohlc_repair="clamp")
    assert fixed.frame["high"][0] == 10.5
    assert fixed.repaired == {"ohlc_clamped": 1}


def test_no_usable_rows_is_an_empty_data_error() -> None:
    raw = _daily([(dt.date(2024, 1, 6), 10.0, 11.0, 9.0, 10.5, 1.0)])  # only a Saturday
    with pytest.raises(EmptyDataError, match="XNYS"):
        normalize_raw(raw, symbol="X", interval="1d", calendar="XNYS")


def test_a_raw_frame_with_the_wrong_timestamp_type_is_refused() -> None:
    raw = _daily([(dt.date(2024, 1, 2), 10.0, 11.0, 9.0, 10.5, 1.0)])
    with pytest.raises(ProviderError, match="datetime"):
        normalize_raw(raw, symbol="X", interval="5m", calendar="XNYS")  # intraday needs a datetime


@pytest.mark.parametrize(
    ("text", "expected"), [("1d", (1, "d")), ("15m", (15, "m")), ("1h", (1, "h"))]
)
def test_parse_interval(text: str, expected: tuple[int, str]) -> None:
    assert parse_interval(text) == expected


@pytest.mark.parametrize("text", ["", "d", "0m", "1w", "1mo", "5x", "-1d"])
def test_parse_interval_refuses_what_providers_do_not_support_yet(text: str) -> None:
    from crucible.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="interval"):
        parse_interval(text)


def _intraday(starts: list[dt.datetime]) -> pl.DataFrame:
    n = len(starts)
    return pl.DataFrame(
        {
            "ts": starts,
            "open": [1.0] * n,
            "high": [2.0] * n,
            "low": [0.5] * n,
            "close": [1.5] * n,
            "volume": [10.0] * n,
        },
        schema={
            "ts": pl.Datetime("us", "UTC"),
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )


def test_an_hourly_bar_that_would_end_after_the_close_ends_at_the_close() -> None:
    # Yahoo's US hourly bars start 09:30, 10:30 ... 15:30 New York; the last one is a half hour long
    starts = [dt.datetime(2024, 1, 2, 14 + h, 30, tzinfo=dt.UTC) for h in range(7)]
    out = normalize_raw(_intraday(starts), symbol="X", interval="1h", calendar="XNYS")
    times = out.frame["event_time"].to_list()
    assert times[0] == 1704209400 * NS  # 10:30 New York
    assert times[-1] == 1704229200 * NS  # 16:00 New York, the XNYS close, not 16:30


def test_a_bar_that_has_not_closed_yet_is_dropped_and_counted() -> None:
    raw = _daily(
        [
            (dt.date(2024, 1, 2), 10.0, 11.0, 9.0, 10.5, 1.0),
            (dt.date(2024, 1, 3), 10.0, 11.0, 9.0, 10.5, 1.0),
        ]
    )
    now = 1704229200 * NS + 1  # just after the close of 2024-01-02
    out = normalize_raw(raw, symbol="X", interval="1d", calendar="XNYS", now_ns=now)
    assert out.frame["event_time"].to_list() == [1704229200 * NS]
    assert out.dropped == {"not_closed": 1}


def test_rows_the_adapter_marked_out_of_range_are_dropped_and_counted() -> None:
    raw = _daily(
        [
            (dt.date(2024, 1, 2), 10.0, 11.0, 9.0, 10.5, 1.0),
            (dt.date(2024, 1, 3), 10.0, 11.0, 9.0, 10.5, 1.0),
        ]
    ).with_columns(in_range=pl.Series([True, False]))
    out = normalize_raw(raw, symbol="X", interval="1d", calendar="XNYS")
    assert out.frame.height == 1
    assert out.dropped == {"out_of_range": 1}


def test_a_missing_or_non_finite_volume_becomes_zero_and_is_counted() -> None:
    raw = _daily(
        [
            (dt.date(2024, 1, 2), 10.0, 11.0, 9.0, 10.5, None),
            (dt.date(2024, 1, 3), 10.0, 11.0, 9.0, 10.5, float("nan")),
            (dt.date(2024, 1, 4), 10.0, 11.0, 9.0, 10.5, 5.0),
        ]
    )
    out = normalize_raw(raw, symbol="X", interval="1d", calendar="XNYS")
    assert out.frame["volume"].to_list() == [0, 0, 5]
    assert out.repaired == {"volume_zeroed": 2}
