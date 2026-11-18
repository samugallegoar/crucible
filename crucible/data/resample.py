"""Causal resampling of a continuous futures series to coarser bars (Fathom C5a).

``resample_session_bars`` turns a one-minute continuous series (``CONTINUOUS_BAR_SCHEMA``, ADR-0086)
into 5- or 15-minute bars whose every bucket lies inside ONE CME Globex session and ONE of its
scheduled segments. Fidelity is a reading resolution, never a licence to look ahead, so the rules
here are the ones that keep the coarser bar an aggregate of bars that had already closed:

- a bucket is the half-open interval of bar ENDS ``(k*m, (k+1)*m]`` minutes on the UTC clock,
  clipped to the session's scheduled segment: a bucket NEVER spans the maintenance break, a halt or
  a session boundary, and a segment whose open or close is not on an ``m``-minute boundary simply
  gets a shorter first/last bucket, flagged ``partial``;
- a bucket's ``event_time`` is the bucket's END clipped to the segment's scheduled close, so a
  label is never later than the close it belongs to;
- ``available_at`` is ``max(bucket end, the latest constituent's available_at)``: the aggregate is
  knowable when its last constituent is, and never before the bucket's label;
- a bucket with no constituent produces NO row (a data gap is not filled by inventing a bar), and
  an off-schedule bar (a print outside every scheduled segment, ADR-0091) is not aggregated at all:
  it is dropped and counted;
- a bucket never mixes contracts: two contracts in one bucket is a series defect and is refused.

The result is a deterministic function of the input rows: only bars at or before a bucket's end
enter it, so removing later bars cannot change an earlier bar (``tests/lookahead``).

Units: times are UTC ``int64`` nanoseconds, ``event_time`` a bar's END (its open is
``event_time - minutes*60s``), prices in the series' points, ``volume`` in contracts, ``bars`` a
count of one-minute constituents from ``Int64``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import NS_PER_S
from crucible.data.cme_sessions import (
    BarSchedule,
    SessionCalendar,
    assign_bars,
    session_trade_dates,
)
from crucible.data.contracts import CONTINUOUS_BAR_SCHEMA

RESOLUTION_MINUTES = (5, 15)
"""The resolutions this resampler builds. One-minute bars are the source series: ``1m`` is the
identity and is never routed through here (the caller keeps the series as it is)."""

REQUIRED_COLUMNS = (
    "event_time",
    "available_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "contract",
)
"""The columns a series must carry to be aggregated (all of ``CONTINUOUS_BAR_SCHEMA`` minus the
optional ``symbol``)."""

_NS_PER_MIN = 60 * NS_PER_S


@dataclass(frozen=True, slots=True)
class ResampleResult:
    """The resampled series and what resampling had to leave out.

    ``bars``: one row per bucket that had at least one one-minute constituent, sorted by
    ``event_time``, carrying ``symbol`` (when the source had it), ``event_time``, ``available_at``,
    OHLC, ``volume``, ``contract`` and the added ``bars`` (constituent count, ``Int64``) and
    ``partial`` (whether the bucket is shorter than ``minutes`` inside its segment, ``Boolean``).
    ``dropped_off_schedule``: one-minute bars outside every scheduled segment, dropped (never
    aggregated: the series' own off-schedule prints are not tradable, ADR-0091).
    ``buckets``: the number of output rows.
    """

    bars: pl.DataFrame
    dropped_off_schedule: int
    buckets: int

    @property
    def partial_buckets(self) -> int:
        """Buckets clipped by their segment's schedule (a short first or last one)."""
        return 0 if self.bars.height == 0 else int(self.bars["partial"].sum())


def _refuse(minutes: object, source_seconds: object) -> tuple[int, int]:
    """The validated ``(minutes, source_seconds)``: only the coarse resolutions this module
    documents, and a bucket that is a whole number of source bars."""
    if (
        isinstance(minutes, bool)
        or not isinstance(minutes, int)
        or minutes not in (RESOLUTION_MINUTES)
    ):
        msg = (
            f"minutes={minutes!r} is not a resampling resolution: build 5- or 15-minute bars "
            f"({list(RESOLUTION_MINUTES)}); one-minute bars are the source series and need no "
            "resampling"
        )
        raise ConfigurationError(msg)
    if (
        isinstance(source_seconds, bool)
        or not isinstance(source_seconds, int)
        or source_seconds < 1
    ):
        msg = f"source_seconds={source_seconds!r} must be a whole number of seconds >= 1"
        raise ConfigurationError(msg)
    if minutes * 60 % source_seconds:
        msg = (
            f"a {minutes}-minute bucket is {minutes * 60}s, which is not a whole number of "
            f"{source_seconds}s source bars: the source series must divide the bucket exactly"
        )
        raise ConfigurationError(msg)
    return minutes, source_seconds


def _segments(placed: BarSchedule) -> tuple[np.ndarray, np.ndarray]:
    """The scheduled segments of every loaded session, as sorted ``(starts, ends)`` arrays."""
    starts: list[int] = []
    ends: list[int] = []
    for session in placed.sessions:
        for start, end in session.segments:
            starts.append(start)
            ends.append(end)
    return np.asarray(starts, dtype=np.int64), np.asarray(ends, dtype=np.int64)


def resample_session_bars(
    bars: pl.DataFrame,
    *,
    calendar: SessionCalendar,
    minutes: int,
    source_seconds: int = 60,
) -> ResampleResult:
    """Aggregate a one-minute continuous futures series into ``minutes``-minute bars.

    ``bars``: the source series (``CONTINUOUS_BAR_SCHEMA``; ``event_time`` is the bar's END).
    ``calendar``: the CME session calendar of the series' root; it decides which bars are on
    schedule and where each bucket is clipped. ``minutes``: 5 or 15. ``source_seconds``: the source
    bar length (60 for one-minute bars).

    Every output row is an aggregate of source rows that ended at or before its ``event_time``, so a
    bar is identical whether or not later bars exist. Refuses a source series with a missing
    column, a duplicated ``event_time`` (two bars ending at one instant have no defined order) and a
    bucket holding two contracts (naming the bucket and both contracts).
    """
    minutes, source_seconds = _refuse(minutes, source_seconds)
    missing = [name for name in REQUIRED_COLUMNS if name not in bars.columns]
    if missing:
        msg = (
            f"the series to resample lacks {missing}: a continuous futures series carries "
            f"{list(CONTINUOUS_BAR_SCHEMA)} (CONTINUOUS_BAR_SCHEMA, ADR-0086)"
        )
        raise DataQualityError(msg)
    ordered = bars.sort("event_time")
    ends = ordered["event_time"].to_numpy().astype(np.int64)
    if ends.size:
        duplicate = np.flatnonzero(np.diff(ends) == 0)
        if duplicate.size:
            at = int(duplicate[0])
            msg = (
                f"two bars end at the same instant ({int(ends[at])} ns): a bucket's open and close "
                "are the first and last constituent, so the series must hold one bar per minute "
                "with strict event_time order"
            )
            raise DataQualityError(msg)
    width = minutes * 60 * NS_PER_S
    _days, on_schedule = session_trade_dates(calendar, ends, source_seconds)
    keep = np.asarray(on_schedule, dtype=np.bool_)
    dropped = int(np.count_nonzero(~keep)) if ends.size else 0
    columns = ["event_time", "available_at", "open", "high", "low", "close", "volume", "contract"]
    if "symbol" in bars.columns:
        columns.insert(0, "symbol")
    kept = ordered.filter(pl.Series("on_schedule", keep, dtype=pl.Boolean)).select(columns)
    if kept.height == 0:
        return ResampleResult(
            bars=pl.DataFrame(schema=_output_schema("symbol" in bars.columns)),
            dropped_off_schedule=dropped,
            buckets=0,
        )

    placed = assign_bars(calendar, kept["event_time"].to_numpy().astype(np.int64), source_seconds)
    seg_starts, seg_ends = _segments(placed)
    kept_ends = kept["event_time"].to_numpy().astype(np.int64)
    position = np.searchsorted(seg_starts, kept_ends, side="right") - 1
    if position.min() < 0 or (kept_ends > seg_ends[position]).any():
        msg = (
            "a bar the session calendar placed on schedule is in no scheduled segment: the "
            "calendar and the bars disagree (re-read the series, this is an engine defect)"
        )
        raise DataQualityError(msg)
    segment_start = seg_starts[position]
    segment_end = seg_ends[position]
    index = (kept_ends - 1) // width
    label = np.minimum((index + 1) * width, segment_end)
    span = np.minimum(label, segment_end) - np.maximum(index * width, segment_start)
    partial = span < width

    grouped = (
        kept.with_columns(
            pl.Series("__bucket", label, dtype=pl.Int64),
            pl.Series("__partial", partial, dtype=pl.Boolean),
        )
        .group_by("__bucket")
        .agg(
            pl.col("contract").n_unique().alias("__contracts"),
            pl.col("contract").first().alias("contract"),
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
            pl.col("available_at").max().alias("__available"),
            pl.len().cast(pl.Int64).alias("bars"),
            pl.col("__partial").first().alias("partial"),
            *([pl.col("symbol").first().alias("symbol")] if "symbol" in kept.columns else []),
        )
        .sort("__bucket")
    )
    mixed = grouped.filter(pl.col("__contracts") != 1)
    if mixed.height:
        bucket = int(mixed["__bucket"][0])
        rows = kept.filter(pl.Series("__bucket", label, dtype=pl.Int64) == bucket)
        contracts = sorted(set(rows["contract"].to_list()))
        msg = (
            f"the {minutes}-minute bucket ending at {bucket} ns holds {len(contracts)} contracts "
            f"({contracts[0]!r} and {contracts[1]!r}): a bucket is one contract's bars, so the "
            "series' roll lands inside a bucket. Resample a series whose contract changes only "
            "between buckets, or use the one-minute series"
        )
        raise DataQualityError(msg)
    out = (
        grouped.select(
            *(["symbol"] if "symbol" in kept.columns else []),
            pl.col("__bucket").alias("event_time"),
            pl.max_horizontal("__available", pl.col("__bucket")).alias("available_at"),
            "open",
            "high",
            "low",
            "close",
            "volume",
            "contract",
            "bars",
            "partial",
        )
        .select(list(_output_schema("symbol" in kept.columns)))
        .cast(pl.Schema(_output_schema("symbol" in kept.columns)))
    )
    buckets = out.height
    return ResampleResult(bars=out, dropped_off_schedule=dropped, buckets=buckets)


def _output_schema(with_symbol: bool) -> dict[str, pl.DataType]:
    """The columns of a resampled series, in the order they are written."""
    schema: dict[str, pl.DataType] = {
        "event_time": pl.Int64(),
        "available_at": pl.Int64(),
        "open": pl.Float64(),
        "high": pl.Float64(),
        "low": pl.Float64(),
        "close": pl.Float64(),
        "volume": pl.Float64(),
        "contract": pl.String(),
        "bars": pl.Int64(),
        "partial": pl.Boolean(),
    }
    if with_symbol:
        return {"symbol": pl.String(), **schema}
    return schema


__all__ = [
    "REQUIRED_COLUMNS",
    "RESOLUTION_MINUTES",
    "ResampleResult",
    "resample_session_bars",
]
