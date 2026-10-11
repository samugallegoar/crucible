"""The one-step backtest on intraday bars (ADR-0072): annualization from the data, bar-count
window checks, intraday timestamps, and the realism re-run on the event-driven engine.

The bars are synthetic but aligned to real XNYS sessions: hourly bars end on the hour from the
open, and the last one ends at the session close, as the yfinance adapter normalizes them."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import TimestampNs
from crucible.data.calendars import get_trading_calendar
from crucible.product.backtest import bars_per_session, periods_per_year_for, run_backtest
from crucible.product.home import Home, resolve_home
from tests.integration.test_product_backtest import request, seed_dataset

HOUR = 3_600 * 10**9
DAY = 24 * HOUR
START, END = dt.date(2021, 1, 4), dt.date(2021, 6, 30)


def _ns(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp() * 1e9)


def _session_bar_ends(start: dt.date, end: dt.date, step_ns: int, calendar: str) -> list[int]:
    """Bar end times like the provider produces: every ``step`` from each session's open, the
    last one clipped to the session close."""
    s, e = TimestampNs(_ns(start)), TimestampNs(_ns(end) + DAY)
    cal = get_trading_calendar(calendar, start=s, end=e)
    stamps: list[int] = []
    for close, open_ in sorted(cal.session_open_by_close(s, e).items()):
        t = open_ + step_ns
        while t < close:
            stamps.append(t)
            t += step_ns
        stamps.append(close)
    return stamps


@pytest.mark.parametrize(
    ("step", "calendar", "expected_bars", "expected_year"),
    [
        (DAY, "XNYS", 1, 252.0),  # daily: unchanged from before ADR-0072
        (HOUR, "XNYS", 7, 7 * 252.0),  # 9:30-10:30 ... 15:30-16:00
        (5 * 60 * 10**9, "XNYS", 78, 78 * 252.0),
        (HOUR, "24/7", 24, 24 * 365.0),
    ],
    ids=["daily", "1h-xnys", "5m-xnys", "1h-24/7"],
)
def test_bars_per_year_come_from_the_session_structure(
    step: int, calendar: str, expected_bars: int, expected_year: float
) -> None:
    if step == DAY:
        s, e = TimestampNs(_ns(START)), TimestampNs(_ns(END) + DAY)
        cal = get_trading_calendar(calendar, start=s, end=e)
        stamps = [int(c) for c in cal.session_closes(s, e)]
    elif calendar == "24/7":
        stamps = list(range(_ns(START) + HOUR, _ns(dt.date(2021, 2, 1)) + 1, HOUR))
    else:
        stamps = _session_bar_ends(START, dt.date(2021, 2, 26), step, calendar)
    assert bars_per_session(stamps, calendar) == expected_bars
    assert periods_per_year_for(stamps, calendar) == expected_year


def _hourly_home(root: Path, *, start: dt.date = START, end: dt.date = END) -> Home:
    stamps = _session_bar_ends(start, end, HOUR, "XNYS")
    rng = np.random.default_rng(20261011)
    # a trending, autocorrelated hourly path so the rules trade
    r = np.empty(len(stamps))
    r[0] = 0.0
    for k in range(1, len(stamps)):
        r[k] = 0.15 * r[k - 1] + 0.0004 + 0.004 * rng.standard_normal()
    closes = 100.0 * np.cumprod(1.0 + r)
    opens = np.r_[100.0, closes[:-1]]
    bars = pl.DataFrame(
        {
            "symbol": ["TRENDY"] * len(stamps),
            "event_time": stamps,
            "available_at": stamps,
            "open": opens,
            "high": np.maximum(opens, closes) * 1.001,
            "low": np.minimum(opens, closes) * 0.999,
            "close": closes,
            "volume": np.full(len(stamps), 1e5),
        }
    )
    home = resolve_home(root / "home")
    seed_dataset(home, ["TRENDY"], start, end, bars, interval="1h")
    return home


@pytest.fixture(scope="module")
def hourly(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    home = _hourly_home(tmp_path_factory.mktemp("intraday"))
    return run_backtest(
        request(
            home,
            symbols=["TRENDY"],
            start=START.isoformat(),
            end=END.isoformat(),
            interval="1h",
            null_iterations=20,
            realism_check=True,
        )
    )


def test_an_hourly_backtest_runs_end_to_end(hourly: dict[str, object]) -> None:
    req, prov, data = hourly["request"], hourly["provenance"], hourly["data"]
    assert isinstance(req, dict)
    assert isinstance(prov, dict)
    assert isinstance(data, dict)
    assert req["interval"] == "1h"
    assert prov["periods_per_year"] == 7 * 252.0  # not 252: an hour is not a day
    assert "T" in str(data["first_bar"])  # intraday stamps carry the time
    assert "calendar_coverage" in data["quality_checks_ran"]


def test_intraday_trades_carry_their_time(hourly: dict[str, object]) -> None:
    trades = hourly["trades"]
    assert isinstance(trades, list)
    assert trades, "the synthetic trend should make the crossover trade"
    first = trades[0]
    assert isinstance(first, dict)
    assert str(first["entry_time"]).endswith("Z")
    assert str(first["exit_time"]) >= str(first["entry_time"])


def test_the_realism_check_reruns_intraday_on_the_event_driven_engine(
    hourly: dict[str, object],
) -> None:
    validation = hourly["validation"]
    assert isinstance(validation, dict)
    assert isinstance(validation["realism_check"], dict)


def test_the_wording_names_the_bar_length(hourly: dict[str, object]) -> None:
    summary = hourly["summary"]
    assert isinstance(summary, dict)
    text = " ".join(str(line) for line in summary["how_much_to_trust"])
    assert "1h-bar returns" in text
    assert "daily returns" not in text


def test_too_few_intraday_bars_for_the_rules_is_refused(tmp_path: Path) -> None:
    short_end = dt.date(2021, 1, 6)  # 3 sessions x 7 bars = 21 bars; sma(30) needs 31
    home = _hourly_home(tmp_path, end=short_end)
    with pytest.raises(ConfigurationError, match="1h bars"):
        run_backtest(
            request(
                home,
                symbols=["TRENDY"],
                start=START.isoformat(),
                end=short_end.isoformat(),
                interval="1h",
                null_iterations=0,
            )
        )
