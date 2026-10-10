"""The yfinance adapter with an injected ``history`` function (ADR-0063). No network and no
``yfinance`` package needed: the fake frame mimics the few things the adapter reads (``index``,
column access and ``empty``).

yfinance facts (its source, verified 2026-10-07): ``Ticker.history(start, end, interval,
auto_adjust)`` takes ``start`` inclusive and ``end`` exclusive; the index is tz-aware in the
exchange's time zone (a daily bar is stamped midnight local, an intraday bar at its start);
``auto_adjust=False`` still returns split-adjusted prices, so a true raw series is not available.

Hand numbers: 2024-01-02 09:30 America/New_York = 14:30Z, so a 5m bar closes 14:35Z = 1704206100;
the Tokyo daily bar of 2024-01-04 is stamped 2024-01-04 00:00 JST = 2024-01-03 15:00Z, and its date
must stay 2024-01-04 (a UTC conversion would give the 3rd); Tokyo closes at 15:00 JST in January
2024 = 06:00Z = 1704348000.
"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.contracts import BAR_SCHEMA
from crucible.data.providers import registry
from crucible.data.providers.errors import (
    EmptyDataError,
    ProviderError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from crucible.data.providers.settings import ProviderSettings
from crucible.data.providers.yfinance import YFinanceProvider

NY = ZoneInfo("America/New_York")
TOKYO = ZoneInfo("Asia/Tokyo")


class _Series:
    def __init__(self, values: Sequence[float | None]) -> None:
        self._values = list(values)

    def tolist(self) -> list[float | None]:
        return self._values


class _Frame:
    """The slice of a pandas DataFrame the adapter uses."""

    def __init__(self, index: list[dt.datetime], **columns: Sequence[float | None]) -> None:
        self.index = index
        self._columns = {name: _Series(values) for name, values in columns.items()}

    @property
    def empty(self) -> bool:
        return not self.index

    def __getitem__(self, name: str) -> _Series:
        return self._columns[name]


def _ohlcv(index: list[dt.datetime]) -> _Frame:
    n = len(index)
    return _Frame(
        index,
        Open=[10.0 + i for i in range(n)],
        High=[11.0 + i for i in range(n)],
        Low=[9.0 + i for i in range(n)],
        Close=[10.5 + i for i in range(n)],
        Volume=[100.0 * (i + 1) for i in range(n)],
    )


class _History:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def __call__(self, symbol: str, **kwargs: Any) -> Any:
        self.calls.append({"symbol": symbol, **kwargs})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _provider(history: _History, **kwargs: Any) -> YFinanceProvider:
    return YFinanceProvider(history=history, sleep=lambda _s: None, **kwargs)


def test_daily_adjusted_bars_ask_for_auto_adjust_and_an_exclusive_end_one_day_later() -> None:
    history = _History(
        _ohlcv([dt.datetime(2024, 1, 2, tzinfo=NY), dt.datetime(2024, 1, 3, tzinfo=NY)])
    )
    frame = _provider(history).get_prices(
        "aapl", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted"
    )
    (call,) = history.calls
    assert call["symbol"] == "AAPL"
    assert call["interval"] == "1d"
    assert call["auto_adjust"] is True
    assert call["start"] == dt.date(2024, 1, 1)
    assert call["end"] == dt.date(2024, 2, 1)  # exclusive in yfinance, inclusive in Crucible
    assert frame.schema == pl.Schema(BAR_SCHEMA)
    assert frame["event_time"].to_list() == [1704229200 * 10**9, 1704315600 * 10**9]
    assert frame["close"].to_list() == [10.5, 11.5]


def test_the_date_of_a_daily_bar_is_its_local_date_not_the_utc_date() -> None:
    history = _History(_ohlcv([dt.datetime(2024, 1, 4, tzinfo=TOKYO)]))
    frame = _provider(history, calendar="XTKS").get_prices(
        "7203.T", dt.date(2024, 1, 4), dt.date(2024, 1, 4), "1d", "adjusted"
    )
    assert frame["event_time"].to_list() == [1704348000 * 10**9]


def test_an_intraday_bar_is_stamped_with_its_start_and_closes_one_interval_later() -> None:
    history = _History(_ohlcv([dt.datetime(2024, 1, 2, 9, 30, tzinfo=NY)]))
    frame = _provider(history).get_prices(
        "AAPL", dt.date(2024, 1, 2), dt.date(2024, 1, 2), "5m", "adjusted"
    )
    assert frame["event_time"].to_list() == [1704206100 * 10**9]
    assert history.calls[0]["interval"] == "5m"


def test_rows_outside_the_requested_range_are_ignored() -> None:
    history = _History(
        _ohlcv([dt.datetime(2024, 1, 2, tzinfo=NY), dt.datetime(2024, 2, 1, tzinfo=NY)])
    )
    frame = _provider(history).get_prices(
        "AAPL", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted"
    )
    assert frame.height == 1


def test_a_raw_series_is_refused_with_the_reason_and_the_alternative() -> None:
    with pytest.raises(ConfigurationError, match=r"(?s)raw.*split-adjusted.*tiingo"):
        _provider(_History(_ohlcv([]))).get_prices(
            "AAPL", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "raw"
        )


def test_an_empty_answer_names_the_likely_causes() -> None:
    with pytest.raises(EmptyDataError, match=r"(?s)AAPL.*delisted.*rate"):
        _provider(_History(_ohlcv([]))).get_prices(
            "AAPL", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted"
        )


def test_a_rate_limit_error_from_yahoo_is_retried_then_reported() -> None:
    class YFRateLimitError(Exception):
        pass

    history = _History(YFRateLimitError("Too Many Requests"))
    sleeps: list[float] = []
    provider = YFinanceProvider(history=history, sleep=sleeps.append)
    with pytest.raises(ProviderRateLimitError, match=r"(?i)unofficial"):
        provider.get_prices("AAPL", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted")
    assert len(history.calls) == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_any_other_failure_is_a_network_error_naming_the_exception_type() -> None:
    history = _History(ConnectionError("dns failure"))
    with pytest.raises(ProviderNetworkError, match="ConnectionError"):
        _provider(history).get_prices(
            "AAPL", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted"
        )


def test_the_info_says_it_is_unofficial_and_adjusted_only() -> None:
    info = YFinanceProvider.info
    assert not info.official
    assert not info.needs_key
    assert info.price_bases == ("adjusted",)
    assert {"1d", "1h", "5m"} <= set(info.intervals)
    assert "unofficial" in info.notes.lower()


def test_the_registry_builds_yfinance_and_a_missing_package_says_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = ProviderSettings.load(environ={}, dotenv_path=tmp_path / "x")
    provider = registry.build_provider(
        "yfinance", settings, calendar="XNYS", history=_History(_ohlcv([]))
    )
    assert provider.info.name == "yfinance"
    monkeypatch.setitem(sys.modules, "yfinance", None)  # an ImportError, as if not installed
    with pytest.raises(ProviderUnavailableError, match=r"uv sync --extra yfinance"):
        registry.build_provider("yfinance", settings, calendar="XNYS")


def test_first_day_intraday_bars_east_of_utc_are_kept() -> None:
    """ASX opens 10:00 AEDT = 23:00Z the day before: the local date decides, not the UTC date."""
    sydney = ZoneInfo("Australia/Sydney")
    history = _History(_ohlcv([dt.datetime(2024, 1, 2, 10, 0, tzinfo=sydney)]))
    fetched = _provider(history, calendar="XASX").fetch_bars(
        "BHP.AX", dt.date(2024, 1, 2), dt.date(2024, 1, 2), "5m", "adjusted"
    )
    assert fetched.frame.height == 1
    assert fetched.dropped == {}


def test_rows_outside_the_range_are_counted_not_silently_dropped() -> None:
    history = _History(
        _ohlcv([dt.datetime(2024, 1, 2, tzinfo=NY), dt.datetime(2024, 2, 1, tzinfo=NY)])
    )
    fetched = _provider(history).fetch_bars(
        "AAPL", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted"
    )
    assert fetched.dropped == {"out_of_range": 1}


def test_a_programming_error_inside_yfinance_is_not_retried_or_called_a_network_error() -> None:
    history = _History(TypeError("unexpected keyword"))
    with pytest.raises(ProviderError, match="TypeError") as info:
        _provider(history).get_prices(
            "AAPL", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted"
        )
    assert not isinstance(info.value, ProviderNetworkError)
    assert len(history.calls) == 1


def test_a_naive_intraday_timestamp_is_a_data_error_not_a_network_error() -> None:
    naive = dt.datetime(2024, 1, 2, 9, 30)  # noqa: DTZ001 - naive on purpose
    history = _History(_ohlcv([naive]))
    with pytest.raises(ProviderError, match="naive") as info:
        _provider(history).get_prices(
            "AAPL", dt.date(2024, 1, 2), dt.date(2024, 1, 2), "5m", "adjusted"
        )
    assert not isinstance(info.value, ProviderNetworkError)
