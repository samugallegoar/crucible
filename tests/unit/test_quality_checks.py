"""Each quality check refuses its specific pathology."""

from __future__ import annotations

import polars as pl
import pytest

from crucible.core.errors import DataQualityError
from crucible.data.calendars import AlwaysOpenCalendar
from crucible.data.quality import run_quality_checks

DAY = 86_400 * 10**9


def _clean_bars() -> pl.DataFrame:
    times = [DAY, 2 * DAY, 3 * DAY]
    return pl.DataFrame(
        {
            "symbol": ["AAA"] * 3,
            "event_time": times,
            "available_at": times,
            "open": [10.0, 10.5, 10.2],
            "high": [10.8, 11.0, 10.6],
            "low": [9.8, 10.2, 10.0],
            "close": [10.5, 10.4, 10.3],
            "volume": [1e5, 1e5, 1e5],
        }
    )


def test_clean_data_passes_all_checks() -> None:
    ran = run_quality_checks(_clean_bars().lazy(), AlwaysOpenCalendar())
    assert len(ran) == 5


def test_duplicate_event_time_is_refused() -> None:
    bars = pl.concat([_clean_bars(), _clean_bars().tail(1)])
    with pytest.raises(DataQualityError, match="sorted_unique_event_times"):
        run_quality_checks(bars.lazy(), AlwaysOpenCalendar())


def test_nonpositive_price_is_refused() -> None:
    bars = _clean_bars().with_columns(
        pl.when(pl.col("event_time") == 2 * DAY).then(-1.0).otherwise(pl.col("low")).alias("low")
    )
    with pytest.raises(DataQualityError, match="positive_prices"):
        run_quality_checks(bars.lazy(), AlwaysOpenCalendar())


def test_ohlc_bounds_violation_is_refused() -> None:
    bars = _clean_bars().with_columns(
        pl.when(pl.col("event_time") == 2 * DAY)
        .then(9.0)  # high below open/close
        .otherwise(pl.col("high"))
        .alias("high")
    )
    with pytest.raises(DataQualityError, match="ohlc_bounds"):
        run_quality_checks(bars.lazy(), AlwaysOpenCalendar())


def test_available_before_event_is_refused() -> None:
    bars = _clean_bars().with_columns((pl.col("available_at") - 1).alias("available_at"))
    with pytest.raises(DataQualityError, match="availability_not_before_event"):
        run_quality_checks(bars.lazy(), AlwaysOpenCalendar())


def test_missing_session_bar_is_refused() -> None:
    bars = _clean_bars().filter(pl.col("event_time") != 2 * DAY)  # hole in the middle
    with pytest.raises(DataQualityError, match="calendar_coverage"):
        run_quality_checks(bars.lazy(), AlwaysOpenCalendar())


def test_skip_without_reason_is_refused() -> None:
    with pytest.raises(DataQualityError, match="without a reason"):
        run_quality_checks(
            _clean_bars().lazy(), AlwaysOpenCalendar(), skip=frozenset({"positive_prices"})
        )


def test_skip_with_reason_runs_the_rest() -> None:
    bars = _clean_bars().filter(pl.col("event_time") != 2 * DAY)
    ran = run_quality_checks(
        bars.lazy(),
        AlwaysOpenCalendar(),
        skip=frozenset({"calendar_coverage"}),
        skip_reason="synthetic gap fixture, gap is intentional",
    )
    assert "calendar_coverage" not in ran
    assert len(ran) == 4


_QUOTES = ("bid_open", "ask_open", "bid_close", "ask_close")


def _quoted(**overrides: float | None) -> pl.DataFrame:
    quotes: dict[str, float | None] = {
        "bid_open": 9.9,
        "ask_open": 10.1,
        "bid_close": 10.4,
        "ask_close": 10.6,
    }
    quotes.update(overrides)
    return _clean_bars().with_columns([pl.lit(v, pl.Float64).alias(k) for k, v in quotes.items()])


def test_quote_columns_are_optional_and_clean_quotes_pass() -> None:
    assert len(run_quality_checks(_quoted().lazy(), AlwaysOpenCalendar())) == 6
    no_quote = _quoted(bid_open=None, ask_open=None, bid_close=None, ask_close=None)
    run_quality_checks(no_quote.lazy(), AlwaysOpenCalendar())  # a bar with no quote is fine
    run_quality_checks(
        _quoted(bid_open=0.0, bid_close=0.0).lazy(), AlwaysOpenCalendar()
    )  # a zero bid is a valid one-sided book


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"bid_open": 10.5}, "crossed"),
        ({"bid_close": -0.01}, "negative"),
        ({"ask_close": 0.0, "bid_close": 0.0}, "ask_not_positive"),
        ({"ask_close": None}, "partial"),
    ],
)
def test_bad_quotes_are_refused(overrides: dict[str, float | None], reason: str) -> None:
    with pytest.raises(DataQualityError, match=f"quote_consistency.*{reason}"):
        run_quality_checks(_quoted(**overrides).lazy(), AlwaysOpenCalendar())


@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
def test_a_non_finite_quote_is_refused(bad: float) -> None:
    with pytest.raises(DataQualityError, match=r"quote_consistency.*non_finite"):
        run_quality_checks(_quoted(ask_open=bad).lazy(), AlwaysOpenCalendar())
