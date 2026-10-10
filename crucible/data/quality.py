"""Data-quality engine: runs before any backtest touches a dataset.

Failures raise ``DataQualityError`` naming the check, the symbol, and the
timestamp. Overrides happen only via config with a logged reason — there is
no silent skip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from crucible.core.errors import DataQualityError

if TYPE_CHECKING:
    from crucible.data.calendars import AlwaysOpenCalendar, ExchangeCalendarAdapter
    from crucible.data.interfaces import TradingCalendar


def _fail(check: str, frame: pl.DataFrame, detail: str) -> None:
    example = frame.head(3).to_dicts()
    msg = (
        f"data-quality check {check!r} failed: {detail}. "
        f"First offending rows: {example}. Fix the dataset or override this "
        "check in config with a logged reason."
    )
    raise DataQualityError(msg)


class SortedUniqueEventTimes:
    """Per symbol, ``event_time`` must be strictly increasing (catches both
    duplicates and out-of-order rows)."""

    name = "sorted_unique_event_times"

    def run(self, frame: pl.LazyFrame, calendar: TradingCalendar | None) -> None:
        bad = (
            frame.sort(["symbol", "event_time"])
            .with_columns(prev=pl.col("event_time").shift(1).over("symbol"))
            .filter(pl.col("prev").is_not_null() & (pl.col("event_time") <= pl.col("prev")))
            .collect()
        )
        if bad.height:
            _fail(self.name, bad, f"{bad.height} duplicate/out-of-order event_time rows")


class PositivePrices:
    name = "positive_prices"

    def run(self, frame: pl.LazyFrame, calendar: TradingCalendar | None) -> None:
        bad = frame.filter(
            (pl.col("open") <= 0)
            | (pl.col("high") <= 0)
            | (pl.col("low") <= 0)
            | (pl.col("close") <= 0)
        ).collect()
        if bad.height:
            _fail(self.name, bad, f"{bad.height} rows with non-positive prices")


class OhlcBounds:
    """``low <= min(open, close) <= max(open, close) <= high``."""

    name = "ohlc_bounds"

    def run(self, frame: pl.LazyFrame, calendar: TradingCalendar | None) -> None:
        bad = frame.filter(
            (pl.col("low") > pl.min_horizontal("open", "close"))
            | (pl.col("high") < pl.max_horizontal("open", "close"))
        ).collect()
        if bad.height:
            _fail(self.name, bad, f"{bad.height} rows violate low<=min(o,c)<=max(o,c)<=high")


class QuoteConsistency:
    """Optional bid/ask columns (ADR-0060): every row is all-null (no quote) or has all four
    quotes with ``0 <= bid <= ask`` and ``ask > 0`` at both the open and the close quote. A frame
    without the columns passes."""

    name = "quote_consistency"

    _COLUMNS = ("bid_open", "ask_open", "bid_close", "ask_close")

    @classmethod
    def applies_to(cls, frame: pl.LazyFrame) -> bool:
        return all(c in frame.collect_schema().names() for c in cls._COLUMNS)

    def run(self, frame: pl.LazyFrame, calendar: TradingCalendar | None) -> None:
        if not self.applies_to(frame):
            return
        present = pl.sum_horizontal([pl.col(c).is_not_null().cast(pl.Int8) for c in self._COLUMNS])
        problems = {
            "partial": (present > 0) & (present < 4),
            "non_finite": pl.any_horizontal(
                [pl.col(c).is_not_null() & ~pl.col(c).is_finite() for c in self._COLUMNS]
            ),
            "negative": (pl.col("bid_open") < 0) | (pl.col("bid_close") < 0),
            "crossed": (pl.col("bid_open") > pl.col("ask_open"))
            | (pl.col("bid_close") > pl.col("ask_close")),
            "ask_not_positive": (pl.col("ask_open") <= 0) | (pl.col("ask_close") <= 0),
        }
        for reason, condition in problems.items():
            bad = frame.filter(condition).collect()
            if bad.height:
                _fail(self.name, bad, f"{bad.height} rows with a {reason} quote")


class AvailabilityNotBeforeEvent:
    """Bars cannot be known before they close: ``available_at >= event_time``
    (ADR-0007). A violation is impossible data, not a warning."""

    name = "availability_not_before_event"

    def run(self, frame: pl.LazyFrame, calendar: TradingCalendar | None) -> None:
        bad = frame.filter(pl.col("available_at") < pl.col("event_time")).collect()
        if bad.height:
            _fail(self.name, bad, f"{bad.height} rows with available_at < event_time")


class CalendarCoverage:
    """Between each symbol's first and last bar, every calendar session close
    must have a bar (missing rows vs calendar)."""

    name = "calendar_coverage"

    def run(self, frame: pl.LazyFrame, calendar: TradingCalendar | None) -> None:
        if calendar is None:
            msg = f"check {self.name!r} requires a calendar"
            raise DataQualityError(msg)
        spans = (
            frame.group_by("symbol")
            .agg(
                first=pl.col("event_time").min(),
                last=pl.col("event_time").max(),
                times=pl.col("event_time").sort(),
            )
            .sort("symbol")
            .collect()
        )
        for row in spans.iter_rows(named=True):
            expected = calendar.session_closes(row["first"], row["last"])
            missing = sorted({int(t) for t in expected} - set(row["times"]))
            if missing:
                msg = (
                    f"data-quality check {self.name!r} failed: symbol {row['symbol']} "
                    f"missing {len(missing)} session bars, first missing ts={missing[0]}. "
                    "Fill the gap or record a delisting/halt in corporate actions."
                )
                raise DataQualityError(msg)


DEFAULT_BAR_CHECKS: tuple[
    SortedUniqueEventTimes
    | PositivePrices
    | OhlcBounds
    | AvailabilityNotBeforeEvent
    | CalendarCoverage,
    ...,
] = (
    SortedUniqueEventTimes(),
    PositivePrices(),
    OhlcBounds(),
    AvailabilityNotBeforeEvent(),
    CalendarCoverage(),
)


def run_quality_checks(
    frame: pl.LazyFrame,
    calendar: ExchangeCalendarAdapter | AlwaysOpenCalendar | None,
    *,
    skip: frozenset[str] = frozenset(),
    skip_reason: str = "",
) -> list[str]:
    """Runs the default bar battery. Skipping any check requires a reason,
    which the caller must log and record in the run manifest. Returns the
    names of the checks that ran."""
    if skip and not skip_reason:
        msg = f"quality checks {sorted(skip)} skipped without a reason; refusing"
        raise DataQualityError(msg)
    ran: list[str] = []
    checks: list[
        SortedUniqueEventTimes
        | PositivePrices
        | OhlcBounds
        | QuoteConsistency
        | AvailabilityNotBeforeEvent
        | CalendarCoverage
    ] = list(DEFAULT_BAR_CHECKS)
    if QuoteConsistency.applies_to(frame):
        # only a frame that carries quote columns runs it, so a plain bar dataset's manifest
        # (quality_checks_ran) is unchanged by the optional columns (ADR-0060)
        checks.insert(3, QuoteConsistency())
    for check in checks:
        if check.name in skip:
            continue
        check.run(frame, calendar)
        ran.append(check.name)
    return ran
