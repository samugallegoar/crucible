"""Minute-level integrity report (ADR-0088). Expected values are counted by hand from the synthetic
bars below, not derived from the code."""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.contracts import BAR_SCHEMA
from crucible.data.integrity import integrity_report

_NS = 1_000_000_000
_MIN = 60 * _NS


def _ns(text: str) -> int:
    return int(dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC).timestamp()) * _NS


def _bar(at: int, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "ES",
        "event_time": at,
        "available_at": at,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 10.0,
    }
    row.update(over)
    return row


def _frame(rows: list[dict[str, object]]) -> pl.LazyFrame:
    return pl.DataFrame(rows, schema=BAR_SCHEMA).lazy()


def _run(rows: list[dict[str, object]], **kwargs: object) -> dict[str, object]:
    return integrity_report(_frame(rows), session="utc", **kwargs)  # type: ignore[arg-type]


def _sym(report: dict[str, object]) -> dict[str, object]:
    symbols = report["symbols"]
    assert isinstance(symbols, list)
    return symbols[0]  # type: ignore[no-any-return]


T0 = _ns("2024-01-02T15:01:00")  # close of the bar that opened 15:00


def test_a_complete_session_has_no_gap_and_is_ok() -> None:
    report = _run([_bar(T0 + i * _MIN) for i in range(5)])
    sym = _sym(report)
    assert report["ok"] is True
    assert (sym["rows"], sym["sessions"], sym["missing_minutes"]) == (5, 1, 0)
    assert (sym["sessions_with_gaps"], sym["largest_gap_minutes"]) == (0, 0)
    assert (sym["first"], sym["last"]) == ("2024-01-02T15:01:00Z", "2024-01-02T15:05:00Z")


def test_missing_minutes_and_the_largest_hole_are_counted_inside_the_session_span() -> None:
    # closes at minutes 0,1,2,6,7: span 0..7 = 8 minutes, 5 present -> 3 missing; the biggest step
    # is 2 -> 6 = 4 minutes, i.e. a hole of 3 missing minutes
    minutes = [0, 1, 2, 6, 7]
    report = _run([_bar(T0 + m * _MIN) for m in minutes])
    sym = _sym(report)
    assert sym["missing_minutes"] == 3
    assert sym["sessions_with_gaps"] == 1
    assert sym["largest_gap_minutes"] == 3
    assert sym["worst_gaps"] == [{"session": "2024-01-02", "missing": 3, "largest_gap": 3}]
    assert report["ok"] is True  # a gap is a finding, not a contract violation


def test_the_time_between_two_sessions_is_not_a_gap() -> None:
    day2 = T0 + 86_400 * _NS
    report = _run(
        [_bar(T0 + i * _MIN) for i in range(3)] + [_bar(day2 + i * _MIN) for i in range(3)]
    )
    sym = _sym(report)
    assert sym["sessions"] == 2
    assert sym["missing_minutes"] == 0


def test_each_contract_violation_is_counted_once_and_makes_the_report_not_ok() -> None:
    rows = [
        _bar(T0),
        _bar(T0 + _MIN),
        _bar(T0 + _MIN),  # duplicate (symbol, event_time)
        _bar(T0 + 2 * _MIN, high=98.0),  # high < low
        _bar(T0 + 3 * _MIN, open=0.0, low=0.0),  # non-positive price (bounds still hold)
        _bar(T0 + 4 * _MIN, available_at=T0),  # available before the bar closed
        _bar(T0 + 5 * _MIN, volume=-1.0),  # negative volume
        _bar(T0 + 6 * _MIN, volume=None),  # null
    ]
    report = _run(rows)
    assert report["ok"] is False
    assert report["errors"] == {
        "duplicate_bars": 1,
        "null_values": 1,
        "nonpositive_price": 1,
        "ohlc_bounds": 1,
        "available_before_event": 1,
        "negative_volume": 1,
    }


def test_a_bar_closing_outside_its_own_open_close_range_is_an_ohlc_violation() -> None:
    rows = [_bar(T0, close=105.0), _bar(T0 + _MIN, open=95.0)]  # close > high; open < low
    assert _run(rows)["errors"]["ohlc_bounds"] == 2  # type: ignore[index]


def test_zero_volume_bars_are_reported_and_are_not_an_error() -> None:
    report = _run([_bar(T0, volume=0.0), _bar(T0 + _MIN)])
    assert _sym(report)["zero_volume_bars"] == 1
    assert report["ok"] is True


def test_short_sessions_are_those_under_half_the_median() -> None:
    def day(n: int, bars: int) -> list[dict[str, object]]:
        start = T0 + n * 86_400 * _NS
        return [_bar(start + i * _MIN) for i in range(bars)]

    # bars per session 10, 10, 2: median 10, threshold 5 -> only the 2-bar session is short
    report = _run(day(0, 10) + day(1, 10) + day(2, 2))
    sym = _sym(report)
    assert sym["median_bars_per_session"] == 10.0
    assert sym["short_sessions"] == 1
    assert sym["short_session_examples"] == [{"session": "2024-01-04", "bars": 2}]


def test_a_saturday_session_is_reported() -> None:
    saturday = _ns("2024-01-06T15:01:00")  # a Saturday
    report = _run([_bar(T0), _bar(saturday)])
    sym = _sym(report)
    assert sym["weekend_sessions"] == 1
    assert sym["weekend_session_examples"] == [{"session": "2024-01-06", "bars": 1}]


def test_the_cme_rule_keeps_a_winter_friday_stub_in_friday() -> None:
    # Friday 2013-01-11 22:00..22:14 UTC opens (16:00..16:14 CST): closes 22:01..22:15
    first_close = _ns("2013-01-11T22:01:00")
    rows = [_bar(first_close + i * _MIN) for i in range(15)]
    sym = _sym(integrity_report(_frame(rows), session="cme"))
    assert sym["weekend_sessions"] == 0
    assert sym["sessions"] == 1
    # the same bars under a UTC-day rule are still Friday; the CME rule must not move them
    assert _sym(integrity_report(_frame(rows), session="utc"))["sessions"] == 1


def test_symbols_are_reported_separately_and_sorted() -> None:
    rows = [_bar(T0 + i * _MIN, symbol="NQ") for i in range(3)]
    rows += [_bar(T0 + i * _MIN, symbol="ES") for i in range(2)]
    report = _run(rows)
    symbols = report["symbols"]
    assert isinstance(symbols, list)
    assert [(s["symbol"], s["rows"]) for s in symbols] == [("ES", 2), ("NQ", 3)]


def test_the_calendar_comparison_lists_session_dates_on_either_side() -> None:
    # data sessions (CME trade dates): Mon 2013-01-14, Tue 01-15 and a Saturday 01-19. CMES has
    # sessions Mon 14, Tue 15, Wed 16, Thu 17, Fri 18 in that range and none on Saturday.
    def bar_on(opened: str) -> dict[str, object]:
        return _bar(_ns(opened) + _MIN)

    rows = [
        bar_on("2013-01-14T15:00:00"),
        bar_on("2013-01-15T15:00:00"),
        bar_on("2013-01-19T15:00:00"),
    ]
    report = integrity_report(_frame(rows), session="cme", calendar="CMES")
    cal = report["calendar"]
    assert isinstance(cal, dict)
    assert cal["range"] == ["2013-01-14", "2013-01-19"]
    assert cal["in_data_not_calendar_examples"] == ["2013-01-19"]
    assert cal["in_calendar_not_data_examples"] == ["2013-01-16", "2013-01-17", "2013-01-18"]
    assert (cal["data_sessions"], cal["calendar_sessions"]) == (3, 5)


def test_without_a_calendar_that_section_is_null() -> None:
    assert _run([_bar(T0)])["calendar"] is None


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"bar_seconds": 0}, "bar_seconds"),
        ({"top": -1}, "top"),
        ({"session": "weekly"}, "session"),
        ({"calendar": "24/7"}, "no session dates"),
    ],
)
def test_refusals_say_what_to_change(kwargs: dict[str, object], match: str) -> None:
    options: dict[str, object] = {"session": "utc"}
    options.update(kwargs)
    with pytest.raises(ConfigurationError, match=match):
        integrity_report(_frame([_bar(T0)]), **options)  # type: ignore[arg-type]


def test_an_empty_dataset_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="no rows"):
        integrity_report(_frame([]), session="utc")


def test_the_report_does_not_depend_on_row_order() -> None:
    rows = [_bar(T0 + m * _MIN) for m in (0, 1, 2, 6, 7)]
    assert _run(rows) == _run(list(reversed(rows)))
