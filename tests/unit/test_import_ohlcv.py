"""Generic OHLCV CSV importer (ADR-0052), hand-computed on small files."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.importers.ohlcv import import_ohlcv
from crucible.data.importers.spec import OhlcvSpec

NS = 10**9


def _ns(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(dt.datetime(year, month, day, hour, minute, tzinfo=dt.UTC).timestamp()) * NS


def _csv(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _spec(pattern: str, **over: Any) -> OhlcvSpec:
    raw: dict[str, Any] = {
        "kind": "ohlcv_csv",
        "dataset": "d",
        "input": pattern,
        "price_basis": "raw",
        "columns": {
            "timestamp": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        },
        "symbol": {"column": "Symbol"},
        "timestamp": {"format": "%Y-%m-%d", "meaning": "session_close", "calendar": "XNYS"},
    }
    raw.update(over)
    return OhlcvSpec.model_validate(raw)


def _bars(spec: OhlcvSpec) -> list[dict[str, Any]]:
    result = import_ohlcv(spec)
    return result.datasets[0].frame.sort(["symbol", "event_time"]).to_dicts()


def test_daily_rows_map_to_the_exchange_session_close_and_non_sessions_are_dropped(
    tmp_path: Path,
) -> None:
    """XNYS closes at 16:00 New York = 21:00 UTC in January; Saturday 2020-01-04 is no session."""
    _csv(
        tmp_path / "eq.csv",
        [
            "Date,Open,High,Low,Close,Volume,Symbol",
            "2020-01-02,10,12,9,11,100,aapl",
            "2020-01-03,11,13,10,12,200,aapl",
            "2020-01-04,12,14,11,13,300,aapl",
        ],
    )
    result = import_ohlcv(_spec(str(tmp_path / "eq.csv"), rows={"max_dropped_fraction": 0.5}))
    frame = result.datasets[0].frame.sort("event_time")
    assert frame["symbol"].to_list() == ["AAPL", "AAPL"]
    assert frame["event_time"].to_list() == [_ns(2020, 1, 2, 21), _ns(2020, 1, 3, 21)]
    assert frame["available_at"].to_list() == frame["event_time"].to_list()
    assert frame["close"].to_list() == [11.0, 12.0]
    assert frame["volume"].to_list() == [100.0, 200.0]
    assert result.report.rows_read == 3
    assert result.report.dropped == {"not_a_session": 1}
    assert result.report.rows_written == {"d": 2}


def test_bar_open_15m_with_a_semicolon_delimiter(tmp_path: Path) -> None:
    _csv(
        tmp_path / "xau.csv",
        [
            "Date;Open;High;Low;Close;Volume",
            "2004.06.11 07:15;384;384.3;383.8;384.3;12",
            "2004.06.11 07:30;383.8;384.3;383.6;383.8;12",
        ],
    )
    spec = _spec(
        str(tmp_path / "xau.csv"),
        delimiter=";",
        symbol={"fixed": "xauusd"},
        timestamp={"format": "%Y.%m.%d %H:%M", "meaning": "bar_open", "interval": "15m"},
    )
    frame = import_ohlcv(spec).datasets[0].frame.sort("event_time")
    assert frame["symbol"].to_list() == ["XAUUSD", "XAUUSD"]
    assert frame["event_time"].to_list() == [_ns(2004, 6, 11, 7, 30), _ns(2004, 6, 11, 7, 45)]


def test_bar_open_daily_closes_at_the_next_midnight(tmp_path: Path) -> None:
    _csv(tmp_path / "g.csv", ["Date,Open,High,Low,Close,Volume", "2004-06-11,1,2,1,2,5"])
    spec = _spec(
        str(tmp_path / "g.csv"),
        symbol={"fixed": "GOLD"},
        timestamp={"format": "%Y-%m-%d", "meaning": "bar_open", "interval": "1d"},
    )
    assert _bars(spec)[0]["event_time"] == _ns(2004, 6, 12)


def test_a_monthly_bar_closes_at_the_next_month_start_across_a_year_end(tmp_path: Path) -> None:
    _csv(
        tmp_path / "m.csv",
        ["Date,Open,High,Low,Close,Volume", "2004-06-01,1,2,1,2,5", "2004-12-01,2,3,2,3,5"],
    )
    spec = _spec(
        str(tmp_path / "m.csv"),
        symbol={"fixed": "GOLD"},
        timestamp={"format": "%Y-%m-%d", "meaning": "bar_open", "interval": "1mo"},
    )
    assert [b["event_time"] for b in _bars(spec)] == [_ns(2004, 7, 1), _ns(2005, 1, 1)]


def test_a_local_timezone_is_converted_to_utc(tmp_path: Path) -> None:
    """2020-01-02 09:30 America/New_York is 14:30 UTC (EST, UTC-5)."""
    _csv(tmp_path / "t.csv", ["Date,Open,High,Low,Close,Volume", "2020-01-02 09:30,1,2,1,2,5"])
    spec = _spec(
        str(tmp_path / "t.csv"),
        symbol={"fixed": "X"},
        timestamp={
            "format": "%Y-%m-%d %H:%M",
            "timezone": "America/New_York",
            "meaning": "bar_close",
        },
    )
    assert _bars(spec)[0]["event_time"] == _ns(2020, 1, 2, 14, 30)


@pytest.mark.parametrize("local", ["2020-11-01 01:30", "2020-03-08 02:30"])
def test_an_ambiguous_or_nonexistent_local_time_is_refused(tmp_path: Path, local: str) -> None:
    _csv(tmp_path / "t.csv", ["Date,Open,High,Low,Close,Volume", f"{local},1,2,1,2,5"])
    spec = _spec(
        str(tmp_path / "t.csv"),
        symbol={"fixed": "X"},
        timestamp={
            "format": "%Y-%m-%d %H:%M",
            "timezone": "America/New_York",
            "meaning": "bar_close",
        },
    )
    with pytest.raises(ConfigurationError, match="ambiguous or non-existent"):
        import_ohlcv(spec)


def test_the_symbol_can_come_from_the_file_name_in_sorted_order(tmp_path: Path) -> None:
    for name in ("msft", "aapl"):
        _csv(tmp_path / f"{name}.csv", ["Date,Open,High,Low,Close,Volume", "2020-01-02,1,2,1,2,5"])
    spec = _spec(str(tmp_path / "*.csv"), symbol={"from_filename": True})
    result = import_ohlcv(spec)
    assert result.report.files == 2
    assert sorted(result.datasets[0].frame["symbol"].to_list()) == ["AAPL", "MSFT"]


def test_a_glob_that_matches_nothing_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="matched no files"):
        import_ohlcv(_spec(str(tmp_path / "*.csv")))


def test_a_missing_declared_column_names_the_file_and_column(tmp_path: Path) -> None:
    _csv(tmp_path / "eq.csv", ["Date,Open,Low,Close,Volume,Symbol", "2020-01-02,1,1,2,5,a"])
    with pytest.raises(ConfigurationError, match=r"eq\.csv.*High"):
        import_ohlcv(_spec(str(tmp_path / "eq.csv")))


def test_incomplete_rows_are_dropped_and_counted(tmp_path: Path) -> None:
    _csv(
        tmp_path / "eq.csv",
        [
            "Date,Open,High,Low,Close,Volume,Symbol",
            "2020-01-02,10,12,9,11,100,a",
            "2020-01-03,11,13,10,,200,a",
        ],
    )
    result = import_ohlcv(_spec(str(tmp_path / "eq.csv"), rows={"max_dropped_fraction": 0.6}))
    assert result.datasets[0].frame.height == 1
    assert result.report.dropped == {"incomplete": 1}


def test_incomplete_rows_can_be_refused(tmp_path: Path) -> None:
    _csv(
        tmp_path / "eq.csv",
        ["Date,Open,High,Low,Close,Volume,Symbol", "2020-01-03,11,13,10,,200,a"],
    )
    spec = _spec(str(tmp_path / "eq.csv"), rows={"on_incomplete": "refuse"})
    with pytest.raises(ConfigurationError, match="incomplete"):
        import_ohlcv(spec)


def test_an_unparsable_number_is_refused_with_an_example(tmp_path: Path) -> None:
    _csv(
        tmp_path / "eq.csv",
        ["Date,Open,High,Low,Close,Volume,Symbol", "2020-01-03,abc,13,10,11,200,a"],
    )
    with pytest.raises(ConfigurationError, match="abc"):
        import_ohlcv(_spec(str(tmp_path / "eq.csv")))


def test_an_unparsable_timestamp_is_refused_with_an_example(tmp_path: Path) -> None:
    _csv(
        tmp_path / "eq.csv",
        ["Date,Open,High,Low,Close,Volume,Symbol", "yesterday,11,13,10,11,200,a"],
    )
    with pytest.raises(ConfigurationError, match="yesterday"):
        import_ohlcv(_spec(str(tmp_path / "eq.csv")))


def test_ohlc_violations_are_clamped_when_opted_in_and_counted(tmp_path: Path) -> None:
    """open 10, high 10.5, low 10.2, close 11: high < max(o,c) and low > min(o,c)."""
    _csv(
        tmp_path / "eq.csv",
        ["Date,Open,High,Low,Close,Volume,Symbol", "2020-01-02,10,10.5,10.2,11,100,a"],
    )
    spec = _spec(
        str(tmp_path / "eq.csv"), rows={"ohlc_repair": "clamp", "max_dropped_fraction": 1.0}
    )
    result = import_ohlcv(spec)
    row = result.datasets[0].frame.row(0, named=True)
    assert (row["open"], row["high"], row["low"], row["close"]) == (10.0, 11.0, 10.0, 11.0)
    assert result.report.repaired == {"ohlc_clamped": 1}


def test_ohlc_violations_are_left_untouched_when_repair_is_refuse(tmp_path: Path) -> None:
    _csv(
        tmp_path / "eq.csv",
        ["Date,Open,High,Low,Close,Volume,Symbol", "2020-01-02,10,10.5,10.2,11,100,a"],
    )
    result = import_ohlcv(_spec(str(tmp_path / "eq.csv")))
    row = result.datasets[0].frame.row(0, named=True)
    assert (row["high"], row["low"]) == (10.5, 10.2)  # the quality battery refuses it later
    assert result.report.repaired == {}


def test_too_many_drops_refuse_the_import(tmp_path: Path) -> None:
    _csv(
        tmp_path / "eq.csv",
        [
            "Date,Open,High,Low,Close,Volume,Symbol",
            "2020-01-02,10,12,9,11,100,a",
            "2020-01-03,,13,10,11,200,a",
            "2020-01-06,,13,10,11,200,a",
        ],
    )
    spec = _spec(str(tmp_path / "eq.csv"), rows={"max_dropped_fraction": 0.5})
    with pytest.raises(ConfigurationError, match="max_dropped_fraction"):
        import_ohlcv(spec)


def test_the_feed_latency_delays_availability(tmp_path: Path) -> None:
    _csv(
        tmp_path / "eq.csv",
        ["Date,Open,High,Low,Close,Volume,Symbol", "2020-01-02,10,12,9,11,100,a"],
    )
    row = _bars(_spec(str(tmp_path / "eq.csv"), feed_latency_s=3))[0]
    assert row["available_at"] == row["event_time"] + 3 * NS


def test_a_missing_volume_column_means_zero_volume(tmp_path: Path) -> None:
    _csv(tmp_path / "g.csv", ["Date,Open,High,Low,Close", "2004-06-11,1,2,1,2"])
    spec = _spec(
        str(tmp_path / "g.csv"),
        symbol={"fixed": "GOLD"},
        columns={
            "timestamp": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
        },
        timestamp={"format": "%Y-%m-%d", "meaning": "bar_open", "interval": "1d"},
    )
    assert _bars(spec)[0]["volume"] == 0.0


def test_a_daily_bar_in_a_dst_zone_closes_at_the_next_local_midnight(tmp_path: Path) -> None:
    """London 2024-10-27 is 25 hours long: the local day ends at 00:00 GMT on the 28th (not 23:00
    UTC on the 27th, which would make the bar available an hour before it closes)."""
    _csv(tmp_path / "d.csv", ["Date,Open,High,Low,Close,Volume", "2024-10-27,1,2,1,2,5"])
    spec = _spec(
        str(tmp_path / "d.csv"),
        symbol={"fixed": "X"},
        timestamp={
            "format": "%Y-%m-%d",
            "timezone": "Europe/London",
            "meaning": "bar_open",
            "interval": "1d",
        },
    )
    assert _bars(spec)[0]["event_time"] == _ns(2024, 10, 28)


def test_a_monthly_bar_in_a_dst_zone_closes_at_the_next_local_month_start(tmp_path: Path) -> None:
    """New York 2024-11-01 00:00 EDT + 1 month = 2024-12-01 00:00 EST = 05:00 UTC."""
    _csv(tmp_path / "m.csv", ["Date,Open,High,Low,Close,Volume", "2024-11-01,1,2,1,2,5"])
    spec = _spec(
        str(tmp_path / "m.csv"),
        symbol={"fixed": "X"},
        timestamp={
            "format": "%Y-%m-%d",
            "timezone": "America/New_York",
            "meaning": "bar_open",
            "interval": "1mo",
        },
    )
    assert _bars(spec)[0]["event_time"] == _ns(2024, 12, 1, 5)


def test_an_hourly_bar_is_elapsed_time_across_a_dst_change(tmp_path: Path) -> None:
    """New York 2024-11-03 00:30 EDT + 2h of elapsed time = 01:30 EST = 06:30 UTC."""
    _csv(tmp_path / "h.csv", ["Date,Open,High,Low,Close,Volume", "2024-11-03 00:30,1,2,1,2,5"])
    spec = _spec(
        str(tmp_path / "h.csv"),
        symbol={"fixed": "X"},
        timestamp={
            "format": "%Y-%m-%d %H:%M",
            "timezone": "America/New_York",
            "meaning": "bar_open",
            "interval": "2h",
        },
    )
    assert _bars(spec)[0]["event_time"] == _ns(2024, 11, 3, 6, 30)


def test_sessions_older_than_the_calendar_default_window_are_still_sessions(tmp_path: Path) -> None:
    """exchange_calendars defaults to the last 20 years; 2005-01-03 is a real XNYS session
    (close 16:00 EST = 21:00 UTC) and must not be dropped as not_a_session."""
    _csv(
        tmp_path / "old.csv",
        ["Date,Open,High,Low,Close,Volume,Symbol", "2005-01-03,10,12,9,11,100,a"],
    )
    result = import_ohlcv(_spec(str(tmp_path / "old.csv")))
    assert result.report.dropped == {}
    assert result.datasets[0].frame["event_time"].to_list() == [_ns(2005, 1, 3, 21)]


def test_a_blank_volume_becomes_zero_and_is_counted(tmp_path: Path) -> None:
    _csv(
        tmp_path / "v.csv",
        [
            "Date,Open,High,Low,Close,Volume,Symbol",
            "2020-01-02,1,2,1,2,,A",
            "2020-01-03,1,2,1,2,5,A",
        ],
    )
    result = import_ohlcv(_spec(str(tmp_path / "v.csv")))
    assert result.datasets[0].frame.sort("event_time")["volume"].to_list() == [0.0, 5.0]
    assert result.report.extra["volume_zeroed"] == 1  # reported, not a "repair"


def test_a_negative_volume_is_refused_with_an_example(tmp_path: Path) -> None:
    _csv(
        tmp_path / "n.csv",
        ["Date,Open,High,Low,Close,Volume,Symbol", "2020-01-02,1,2,1,2,-5,A"],
    )
    with pytest.raises(ConfigurationError, match=r"negative volume.*-5"):
        import_ohlcv(_spec(str(tmp_path / "n.csv")))


def test_a_file_with_only_a_header_is_refused(tmp_path: Path) -> None:
    _csv(tmp_path / "h.csv", ["Date,Open,High,Low,Close,Volume,Symbol"])
    with pytest.raises(ConfigurationError, match="no data rows"):
        import_ohlcv(_spec(str(tmp_path / "h.csv")))
