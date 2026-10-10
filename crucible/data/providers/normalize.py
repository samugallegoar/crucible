"""Provider-neutral raw bars -> ``BAR_SCHEMA`` bars (ADR-0063).

The raw contract every adapter returns: columns ``ts``, ``open``, ``high``, ``low``, ``close``,
``volume`` (Float64; volume may be null). ``ts`` is a ``Date`` (the session date) for a daily
interval, or a UTC ``Datetime`` (the bar **start**) for an intraday one. Nothing else is assumed
about the provider: its index, time zone and column names are the adapter's business.

Output ``event_time`` is the bar **close** in UTC ns (knowable only once the bar has closed):
an exchange-calendar daily bar closes at that session's close, a ``24/7`` daily bar one day after
its open, an intraday bar at its start plus the interval. ``available_at`` adds the feed latency.
Rows that cannot be used are dropped and **counted**, never silently.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Literal

import polars as pl

from crucible.core.errors import ConfigurationError
from crucible.data.contracts import BAR_SCHEMA
from crucible.data.importers.common import NS_PER_S, clamp_ohlc, ohlc_violation, session_close_table
from crucible.data.providers.errors import EmptyDataError, ProviderError

_PRICES = ("open", "high", "low", "close")
_INTERVAL = re.compile(r"^([1-9][0-9]*)(m|h|d)$")
_NS_PER_DAY = 86_400 * NS_PER_S


@dataclass(frozen=True, slots=True)
class Normalized:
    frame: pl.DataFrame
    dropped: dict[str, int] = field(default_factory=dict)
    repaired: dict[str, int] = field(default_factory=dict)


ROUNDING_TOLERANCE = 1e-6
"""Relative size (of the close) up to which ``ohlc_repair="clamp_rounding"`` treats an OHLC
violation as float rounding of an adjusted series (Yahoo's adjusted SPY has bars whose high is
3e-14 below the close) rather than bad data."""


def parse_interval(interval: str) -> tuple[int, str]:
    """``'5m'`` -> ``(5, 'm')``. Minutes, hours and days only: weekly and monthly bars have no
    single close instant without a rule this layer does not invent (ADR-0063)."""
    match = _INTERVAL.match(interval)
    if match is None:
        msg = (
            f"interval {interval!r} is not supported: use a whole number of minutes, hours or "
            "days such as 1m, 5m, 15m, 1h or 1d (weekly and monthly bars are not supported)"
        )
        raise ConfigurationError(msg)
    return int(match.group(1)), match.group(2)


def normalize_raw(
    raw: pl.DataFrame,
    *,
    symbol: str,
    interval: str,
    calendar: str,
    feed_latency_s: int = 0,
    ohlc_repair: Literal["refuse", "clamp", "clamp_rounding"] = "refuse",
    now_ns: int | None = None,
) -> Normalized:
    """The raw frame as sorted, de-duplicated ``BAR_SCHEMA`` bars plus counts of what was dropped
    (``incomplete``, ``not_a_session``, ``duplicate``, ``not_closed``) or repaired
    (``ohlc_clamped``). An OHLC violation is left for the quality battery to refuse unless
    ``ohlc_repair="clamp"`` (every violation) or ``"clamp_rounding"`` (only a violation within
    ``ROUNDING_TOLERANCE`` of the bar's close, the float noise of an adjusted series; a larger one
    is left for the battery to refuse).

    An intraday bar on an exchange calendar never closes after its session's close (Yahoo's hourly
    bars start at 09:30, so the last one is a half hour long). With ``now_ns`` (UTC ns, supplied by
    the I/O boundary), a bar whose close is after it is still forming and is dropped and counted
    as ``not_closed``: a provider returns today's unfinished bar with a last-trade "close"."""
    _, unit = parse_interval(interval)
    intraday = unit in {"m", "h"}
    expected = "datetime" if intraday else "date"
    ts_dtype = raw.schema["ts"]
    if (intraday and not isinstance(ts_dtype, pl.Datetime)) or (
        not intraday and ts_dtype != pl.Date
    ):
        msg = (
            f"the provider adapter returned ts of type {ts_dtype} for interval {interval!r}; "
            f"a {expected} column was expected (adapter bug, not a data problem)"
        )
        raise ProviderError(msg)

    dropped: dict[str, int] = {}
    repaired: dict[str, int] = {}
    if "in_range" in raw.columns:
        # the adapter knows the exchange's local date; the rows outside the request are counted
        n_out = raw.filter(~pl.col("in_range")).height
        if n_out:
            dropped["out_of_range"] = n_out
        raw = raw.filter(pl.col("in_range")).drop("in_range")
    frame = raw.select("ts", *_PRICES, "volume").with_columns(
        pl.col("volume").cast(pl.Float64), *[pl.col(c).cast(pl.Float64) for c in _PRICES]
    )
    incomplete = pl.any_horizontal(
        pl.col("ts").is_null(),
        *[pl.col(c).is_null() | ~pl.col(c).is_finite() for c in _PRICES],
    )
    n_incomplete = frame.filter(incomplete).height
    if n_incomplete:
        dropped["incomplete"] = n_incomplete
        frame = frame.filter(~incomplete)
    bad_volume = frame.filter(pl.col("volume").is_null() | ~pl.col("volume").is_finite()).height
    if bad_volume:
        repaired["volume_zeroed"] = bad_volume
    frame = frame.with_columns(
        volume=pl.when(pl.col("volume").is_finite()).then(pl.col("volume")).otherwise(0.0)
    )

    if intraday:
        count, step = parse_interval(interval)
        frame = frame.with_columns(
            event_time=pl.col("ts")
            .dt.convert_time_zone("UTC")
            .dt.offset_by(f"{count}{step}")
            .dt.epoch("ns"),
            start_ns=pl.col("ts").dt.convert_time_zone("UTC").dt.epoch("ns"),
        )
        if calendar != "24/7" and frame.height:
            frame = _clip_to_session_close(frame, calendar)
    elif calendar == "24/7":
        frame = frame.with_columns(
            event_time=pl.col("ts").cast(pl.Datetime("ns")).dt.epoch("ns") + _NS_PER_DAY
        )
    else:
        if frame.height:
            first, last = frame["ts"].min(), frame["ts"].max()
            assert isinstance(first, dt.date)
            assert isinstance(last, dt.date)
            table = session_close_table(first, last, calendar)
        else:
            table = pl.DataFrame(schema={"day": pl.Date, "close_ns": pl.Int64})
        frame = frame.join(table, left_on="ts", right_on="day", how="left").rename(
            {"close_ns": "event_time"}
        )
        n_missing = frame.filter(pl.col("event_time").is_null()).height
        if n_missing:
            dropped["not_a_session"] = n_missing
            frame = frame.filter(pl.col("event_time").is_not_null())

    if now_ns is not None:
        unfinished = frame.filter(pl.col("event_time") > now_ns).height
        if unfinished:
            dropped["not_closed"] = unfinished
            frame = frame.filter(pl.col("event_time") <= now_ns)

    # the same bar twice (a provider restating its last row): the later row wins, and it is counted
    before = frame.height
    frame = frame.sort("event_time", maintain_order=True).unique(
        subset="event_time", keep="last", maintain_order=True
    )
    if frame.height != before:
        dropped["duplicate"] = before - frame.height

    violation = ohlc_violation()
    if ohlc_repair == "clamp_rounding":
        # how far outside [low, high] the open/close sit, relative to the close
        excess = (
            pl.max_horizontal(
                pl.max_horizontal("open", "close") - pl.col("high"),
                pl.col("low") - pl.min_horizontal("open", "close"),
                pl.col("low") - pl.col("high"),
            )
            / pl.col("close").abs()
        )
        violation = violation & (excess <= ROUNDING_TOLERANCE)
    n_violations = frame.filter(violation).height
    if n_violations and ohlc_repair in ("clamp", "clamp_rounding"):
        repaired["ohlc_clamped"] = n_violations
        frame = clamp_ohlc(frame, violation)

    if frame.height == 0:
        detail = f" (dropped: {dropped})" if dropped else ""
        msg = (
            f"no usable {interval} rows for {symbol.upper()}{detail}; the range may be outside "
            f"the market's sessions ({calendar}) or the provider returned nothing valid"
        )
        raise EmptyDataError(msg)

    out = (
        frame.with_columns(
            symbol=pl.lit(symbol.upper()),
            available_at=pl.col("event_time") + feed_latency_s * NS_PER_S,
        )
        .select(list(BAR_SCHEMA))
        .cast(BAR_SCHEMA)  # type: ignore[arg-type]
        .sort("event_time")
    )
    return Normalized(frame=out, dropped=dropped, repaired=repaired)


def _clip_to_session_close(frame: pl.DataFrame, calendar: str) -> pl.DataFrame:
    """``event_time = min(start + interval, close of the session the bar starts in)``."""
    first = dt.datetime.fromtimestamp(int(frame["start_ns"].min()) / 1e9, dt.UTC).date()  # type: ignore[arg-type]
    last = dt.datetime.fromtimestamp(int(frame["start_ns"].max()) / 1e9, dt.UTC).date()  # type: ignore[arg-type]
    closes = session_close_table(
        first - dt.timedelta(days=1), last + dt.timedelta(days=1), calendar
    )
    closes = closes.select("close_ns").sort("close_ns")
    joined = (
        frame.with_columns(probe=pl.col("start_ns") + 1)
        .sort("probe")
        .join_asof(closes, left_on="probe", right_on="close_ns", strategy="forward")
    )
    return joined.with_columns(
        event_time=pl.min_horizontal("event_time", pl.col("close_ns").fill_null(2**62))
    ).drop("start_ns", "probe", "close_ns")
