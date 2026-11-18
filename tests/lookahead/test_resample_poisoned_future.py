"""Poisoned-future harness for causal resampling (Fathom C5a, AGENTS.md §7, §9).

A coarser resolution is a reading of the one-minute series, never a licence to look ahead. Three
guarantees, at the value level:

- a resampled bar whose ``event_time`` is at or before a cutoff does not change when every
  one-minute bar after the cutoff is poisoned (or removed outright): the bucket aggregates only
  constituents that had closed by its label;
- the decided targets of a coarse run (5 and 15 minutes) at or before the cutoff are unchanged by
  the same poison, so the session masks and the strategy see nothing from the future;
- ``available_at`` at or before the cutoff is unchanged too: a bucket is knowable when its last
  constituent is, and a poisoned later bar cannot move that instant backwards.

The bars sit on a real ES Globex session (2024-03-05, 09:01 .. 13:20 Chicago) inside one scheduled
segment, so the buckets are clipped by the real schedule.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.continuous import calendar_for
from crucible.data.contracts import CONTINUOUS_BAR_SCHEMA
from crucible.data.resample import resample_session_bars
from crucible.dsl import compile_expression
from crucible.experiments.futures_signals import (
    DatasetRef,
    FuturesSessionPolicy,
    futures_targets,
)

pytestmark = pytest.mark.lookahead

BARS = 260
CUTOFF = 150
SECOND = 1_000_000_000
MINUTE = 60 * SECOND
CALENDAR = calendar_for("ES")
EXEC_REF = DatasetRef("es_1m_cont_v3", "a" * 64, "raw", "none")
SIG_REF = DatasetRef("es_1m_cont_ratio_v3", "b" * 64, "adjusted", "ratio")
SIGNAL = "sign(ts_zscore(close, $n:int[5,20]=10))"


def utc(wall: str) -> int:
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def bar_times() -> list[int]:
    start = dt.datetime.fromisoformat("2024-03-05T09:01:00")
    return [utc((start + dt.timedelta(minutes=index)).isoformat()) for index in range(BARS)]


def closes(seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 4400.0 * np.cumprod(1.0 + rng.normal(0.0, 0.0004, BARS))


def series(values: np.ndarray) -> pl.DataFrame:
    times = bar_times()
    return pl.DataFrame(
        {
            "symbol": ["ES"] * BARS,
            "event_time": times,
            "available_at": [value + 1 for value in times],
            "open": values,
            "high": values * 1.001,
            "low": values * 0.999,
            "close": values,
            "volume": [100.0] * BARS,
            "contract": ["ESH2024"] * BARS,
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )


def poison_from(frame: pl.DataFrame, cutoff_time: int, factor: float = 1e6) -> pl.DataFrame:
    """``frame`` with every price at or after ``cutoff_time`` scaled: an absurd future."""
    return frame.with_columns(
        pl.when(pl.col("event_time") >= cutoff_time)
        .then(pl.col(name) * factor)
        .otherwise(pl.col(name))
        .alias(name)
        for name in ("open", "high", "low", "close")
    )


def poison_shape_from(frame: pl.DataFrame, cutoff_time: int) -> pl.DataFrame:
    """``frame`` with every bar at or after ``cutoff_time`` replaced by a wildly different price
    path (a shape, not a constant factor: a scale-invariant expression is immune to a factor)."""
    ramp = 1_000_000.0 + pl.int_range(pl.len()) * 100_000.0
    return frame.with_columns(
        pl.when(pl.col("event_time") >= cutoff_time).then(ramp).otherwise(pl.col(name)).alias(name)
        for name in ("open", "high", "low", "close")
    )


def resample(frame: pl.DataFrame, minutes: int):
    return resample_session_bars(frame, calendar=CALENDAR, minutes=minutes)


def target_values(frame: pl.DataFrame, minutes: int) -> list[int]:
    """The decided targets of a coarse run over ``frame`` (already resampled)."""
    return (
        futures_targets(
            root="ES",
            execution_bars=frame,
            signal_bars=frame,
            execution_ref=EXEC_REF,
            signal_ref=SIG_REF,
            strategy=compile_expression(SIGNAL),
            contracts=1,
            signal_input="ratio_adjusted",
            session=FuturesSessionPolicy(),
            bar_seconds=minutes * 60,
        )
        .targets["target"]
        .to_list()
    )


def test_a_resampled_bar_at_or_before_the_cutoff_ignores_a_poisoned_future() -> None:
    clean = series(closes())
    cutoff_time = bar_times()[CUTOFF]
    dirty = poison_from(clean, cutoff_time)
    for minutes in (5, 15):
        full = resample(clean, minutes)
        poisoned = resample(dirty, minutes)
        kept = full.bars.filter(pl.col("event_time") <= cutoff_time)
        assert kept.equals(poisoned.bars.filter(pl.col("event_time") <= cutoff_time))
        assert kept.height > 0
        # the poison really is in the later buckets: it is not that nothing changed anywhere
        assert full.bars["close"].to_list() != poisoned.bars["close"].to_list()


def test_a_resampled_bar_at_or_before_the_cutoff_is_the_same_when_later_bars_are_removed() -> None:
    frame = series(closes())
    cutoff_time = bar_times()[CUTOFF]
    for minutes in (5, 15):
        full = resample(frame, minutes)
        truncated = resample(frame.filter(pl.col("event_time") <= cutoff_time), minutes)
        kept = full.bars.filter(pl.col("event_time") <= cutoff_time)
        assert kept.height > 0
        assert kept.equals(truncated.bars.filter(pl.col("event_time") <= cutoff_time))


def test_available_at_at_or_before_the_cutoff_is_not_moved_by_a_poisoned_future() -> None:
    clean = series(closes())
    cutoff_time = bar_times()[CUTOFF]
    dirty = poison_from(clean, cutoff_time).with_columns(
        pl.when(pl.col("event_time") >= cutoff_time)
        .then(pl.col("available_at") + 10 * SECOND)
        .otherwise(pl.col("available_at"))
        .alias("available_at")
    )
    for minutes in (5, 15):
        full = resample(clean, minutes).bars.filter(pl.col("event_time") <= cutoff_time)
        poisoned = resample(dirty, minutes).bars.filter(pl.col("event_time") <= cutoff_time)
        assert full["available_at"].to_list() == poisoned["available_at"].to_list()
        # and the aggregate is never known before its own label
        assert all(
            int(available) >= int(label)
            for available, label in zip(
                full["available_at"].to_list(), full["event_time"].to_list(), strict=True
            )
        )


def test_the_decided_targets_at_or_before_the_cutoff_ignore_a_poisoned_future() -> None:
    clean = series(closes())
    cutoff_time = bar_times()[CUTOFF]
    dirty = poison_shape_from(clean, cutoff_time)
    for minutes in (5, 15):
        full = resample(clean, minutes)
        poisoned = resample(dirty, minutes)
        assert full.bars["event_time"].to_list() == poisoned.bars["event_time"].to_list()
        before = target_values(full.bars, minutes)
        after = target_values(poisoned.bars, minutes)
        labels = full.bars["event_time"].to_list()
        up_to = max(index for index, label in enumerate(labels) if int(label) <= cutoff_time)
        assert before[: up_to + 1] == after[: up_to + 1]
        assert before != after  # the poisoned future really does change the later decisions
