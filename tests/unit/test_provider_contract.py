"""Every provider returns the same normalized format (ADR-0063).

The same two logical daily bars are served through the Tiingo adapter (mocked HTTP) and the
yfinance adapter (injected history function); the frames must be identical in schema, dtypes,
ordering, values, UTC time semantics and column order, whatever the provider.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Mapping
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from crucible.data.contracts import BAR_SCHEMA
from crucible.data.providers.base import PriceProvider
from crucible.data.providers.http import HttpResponse, RetryPolicy
from crucible.data.providers.settings import ApiKey
from crucible.data.providers.tiingo import TiingoProvider
from crucible.data.providers.yfinance import YFinanceProvider

NY = ZoneInfo("America/New_York")
BARS = [  # date, open, high, low, close, volume
    (dt.date(2024, 1, 2), 50.0, 51.0, 49.5, 50.5, 2000.0),
    (dt.date(2024, 1, 3), 50.5, 52.0, 50.0, 51.5, 2400.0),
]


def _tiingo() -> PriceProvider:
    rows = [
        {
            "date": f"{d.isoformat()}T00:00:00.000Z",
            "adjOpen": o,
            "adjHigh": h,
            "adjLow": low,
            "adjClose": c,
            "adjVolume": v,
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "close": 0.0,
            "volume": 0,
        }
        for d, o, h, low, c, v in BARS
    ]

    def transport(url: str, headers: Mapping[str, str]) -> HttpResponse:
        return HttpResponse(200, {}, json.dumps(rows).encode("utf-8"))

    return TiingoProvider(
        ApiKey("tk"),
        transport=transport,
        retry=RetryPolicy(max_attempts=1),
        sleep=lambda _s: None,
        calendar="XNYS",
    )


class _Series:
    def __init__(self, values: list[float]) -> None:
        self._values = values

    def tolist(self) -> list[float]:
        return self._values


class _Frame:
    def __init__(self, keep: list[int] | None = None) -> None:
        picked = list(range(len(BARS))) if keep is None else keep
        self.rows = [BARS[i] for i in picked]
        self.index = [
            dt.datetime(BARS[i][0].year, BARS[i][0].month, BARS[i][0].day, tzinfo=NY)
            for i in picked
        ]
        self.empty = not picked

    def __getitem__(self, name: str) -> _Series:
        position = {"Open": 1, "High": 2, "Low": 3, "Close": 4, "Volume": 5}[name]
        return _Series([row[position] for row in self.rows])


def _yfinance() -> PriceProvider:
    def history(symbol: str, **kwargs: Any) -> _Frame:
        # a real Yahoo answer honours start (inclusive) and end (exclusive)
        keep = [i for i, bar in enumerate(BARS) if kwargs["start"] <= bar[0] < kwargs["end"]]
        return _Frame(keep)

    return YFinanceProvider(history=history, sleep=lambda _s: None, calendar="XNYS")


FACTORIES: dict[str, Callable[[], PriceProvider]] = {"tiingo": _tiingo, "yfinance": _yfinance}


@pytest.mark.parametrize("name", sorted(FACTORIES))
def test_each_provider_returns_bar_schema(name: str) -> None:
    frame = FACTORIES[name]().get_prices(
        "AAPL", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted"
    )
    assert frame.schema == pl.Schema(BAR_SCHEMA)
    assert frame.columns == list(BAR_SCHEMA)
    assert frame["event_time"].is_sorted()
    assert frame.height == len(BARS)


def test_both_providers_return_the_identical_frame_for_the_same_bars() -> None:
    frames = {
        name: factory().get_prices(
            "AAPL", dt.date(2024, 1, 1), dt.date(2024, 1, 31), "1d", "adjusted"
        )
        for name, factory in FACTORIES.items()
    }
    assert frames["tiingo"].equals(frames["yfinance"])
    assert frames["tiingo"]["event_time"].to_list() == [1704229200 * 10**9, 1704315600 * 10**9]


def test_the_yfinance_fake_honours_the_requested_range() -> None:
    frame = _yfinance().get_prices(
        "AAPL", dt.date(2024, 1, 3), dt.date(2024, 1, 31), "1d", "adjusted"
    )
    assert frame.height == 1  # the 2024-01-02 bar is before the start
