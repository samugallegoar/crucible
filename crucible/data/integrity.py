"""Minute-level integrity report of a bar dataset (Fathom C2, ADR-0088).

``crucible data check`` refuses a dataset with a hard defect and passes everything else; it says
nothing about *how complete* a minute dataset is. This report does, from the minutes actually
present: per symbol and per session it counts the bars, the minutes missing inside the session's own
span, the largest hole, the sessions far shorter than the symbol's usual one (half days, holiday
stubs), sessions on a weekend, and the rows that break the data contract. It never repairs or drops
anything and it never decides that a gap is acceptable: the caller reads the numbers.

Timing: a bar's ``event_time`` is its close (UTC ns); its session is a function of its own
timestamp and the published CME schedule, so the report needs no lookahead. Under the ``cme``
rule the trade date comes from the CME session calendar (``cme_sessions``, ADR-0092); bars outside
the calendar's coverage get no session and are counted (``outside_calendar_bars``), never dated by
a guess. An ``exchange_calendars`` calendar is optional and is compared for session *dates* only
(``CMES`` models a 24 h block with no maintenance break or early closes, ADR-0087).
"""

from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING, Literal

import polars as pl

from crucible.core.errors import ConfigurationError
from crucible.core.types import NS_PER_S, TimestampNs
from crucible.data.calendars import ExchangeCalendarAdapter, get_trading_calendar
from crucible.data.cme_session_table import cme_session_table
from crucible.data.cme_sessions import SessionCalendar, coverage_span, session_trade_dates

if TYPE_CHECKING:
    from crucible.data.calendars import AlwaysOpenCalendar

SessionRule = Literal["cme", "utc"]
SHORT_SESSION_FRACTION = 0.5
"""A session with fewer than this share of the symbol's median bars per session is *short*."""

_ERROR_COLUMNS = (
    "duplicate_bars",
    "null_values",
    "nonpositive_price",
    "ohlc_bounds",
    "available_before_event",
    "negative_volume",
)


def _iso(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / NS_PER_S, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


_ROOT = re.compile(r"([A-Z0-9]+?)(?:[FGHJKMNQUVXZ]\d{4})?")


def _root_of(symbol: str) -> str:
    """The futures root of a contract (``ESH2024`` -> ``ES``) or continuous (``ES``) symbol."""
    match = _ROOT.fullmatch(symbol)
    return match.group(1) if match else symbol


def _with_sessions(frame: pl.LazyFrame, rule: SessionRule, bar_seconds: int) -> pl.LazyFrame:
    """``frame`` plus a ``session`` date column; null for a bar outside the CME calendar."""
    bar_ns = bar_seconds * NS_PER_S
    if rule == "utc":
        return frame.with_columns(
            session=pl.from_epoch(pl.col("event_time") - bar_ns, time_unit="ns").dt.date()
        )
    table = cme_session_table()
    roots = frame.select(pl.col("symbol").unique()).collect()["symbol"].to_list()
    by_root: dict[str, list[str]] = {}
    for symbol in roots:
        by_root.setdefault(_root_of(str(symbol)), []).append(str(symbol))
    lookups: list[pl.DataFrame] = []
    for root, symbols in sorted(by_root.items()):
        if root not in table.coverage:
            msg = (
                f"symbol {symbols[0]!r} (root {root!r}) is not in the CME session calendar "
                f"{table.version} (roots {sorted(table.coverage)}); use session='utc' "
                "(CLI --session utc) for a dataset that is not a CME equity-index future"
            )
            raise ConfigurationError(msg)
        calendar = SessionCalendar(table, root)
        ends = (
            frame.filter(pl.col("symbol").is_in(symbols))
            .select(pl.col("event_time").unique().sort())
            .collect()["event_time"]
        )
        first_open, last_close = coverage_span(calendar)
        inside = ends.filter((ends - bar_ns >= first_open) & (ends <= last_close))
        days, _ = session_trade_dates(calendar, inside.to_numpy(), bar_seconds)
        lookups.append(
            pl.DataFrame(
                {
                    "_root": [root] * inside.len(),
                    "event_time": inside,
                    "session": pl.Series(days).cast(pl.Date),
                }
            )
        )
    lookup = pl.concat(lookups) if lookups else None
    root_of = {symbol: root for root, symbols in by_root.items() for symbol in symbols}
    keyed = frame.with_columns(
        _root=pl.col("symbol").replace_strict(root_of, return_dtype=pl.String)
    )
    if lookup is None:
        return keyed.with_columns(session=pl.lit(None, dtype=pl.Date)).drop("_root")
    return keyed.join(lookup.lazy(), on=["_root", "event_time"], how="left").drop("_root")


def integrity_report(
    frame: pl.LazyFrame,
    *,
    bar_seconds: int = 60,
    session: SessionRule = "cme",
    calendar: str | None = None,
    top: int = 10,
) -> dict[str, object]:
    """The integrity report of a bar dataset (``BAR_SCHEMA`` columns), as a JSON-ready dict.

    ``bar_seconds`` is the bar length (``event_time`` is the close, so the open is
    ``event_time - bar_seconds``); ``session`` is how a bar is assigned to a session: ``cme`` is
    the Globex trade date from the CME session calendar (ADR-0092; the root is read from the
    symbols, bars outside the calendar's coverage are counted in ``outside_calendar_bars`` and
    left out of the session statistics), ``utc`` the UTC date of the open.
    ``calendar`` (an ``exchange_calendars`` name such as ``CMES``) adds a comparison of session
    dates. ``top`` bounds the examples listed per finding.

    ``ok`` is False only for rows that break the contract (``errors``): duplicates, nulls,
    non-positive prices, OHLC outside its own bounds, ``available_at < event_time``, negative
    volume. Gaps and short sessions are findings, not errors: a halt or an early close is real.
    """
    if bar_seconds < 1 or top < 0:
        msg = f"bar_seconds must be >= 1 and top >= 0, got {bar_seconds} and {top}"
        raise ConfigurationError(msg)
    if session not in ("cme", "utc"):
        msg = f"session {session!r} is not supported; use 'cme' (Globex trade date) or 'utc'"
        raise ConfigurationError(msg)
    bar_ns = bar_seconds * NS_PER_S

    prices = ("open", "high", "low", "close")
    base = (
        frame.group_by("symbol")
        .agg(
            rows=pl.len(),
            first=pl.col("event_time").min(),
            last=pl.col("event_time").max(),
            duplicate_bars=pl.len() - pl.col("event_time").n_unique(),
            null_values=pl.sum_horizontal(
                pl.col(*prices, "volume", "event_time", "available_at").is_null().sum()
            ),
            nonpositive_price=pl.any_horizontal(*(pl.col(p) <= 0 for p in prices)).sum(),
            ohlc_bounds=(
                (pl.col("high") < pl.col("low"))
                | (pl.col("high") < pl.max_horizontal("open", "close"))
                | (pl.col("low") > pl.min_horizontal("open", "close"))
            ).sum(),
            available_before_event=(pl.col("available_at") < pl.col("event_time")).sum(),
            negative_volume=(pl.col("volume") < 0).sum(),
            zero_volume_bars=(pl.col("volume") == 0).sum(),
        )
        .sort("symbol")
        .collect()
    )
    if base.height == 0:
        msg = "the dataset has no rows; build it before checking its integrity"
        raise ConfigurationError(msg)

    dated = _with_sessions(frame, session, bar_seconds)
    outside = dict(
        dated.filter(pl.col("session").is_null())
        .group_by("symbol")
        .agg(pl.len())
        .collect()
        .iter_rows()
    )
    sessions = (
        dated.filter(pl.col("session").is_not_null())
        .group_by(["symbol", "session"])
        .agg(
            bars=pl.col("event_time").n_unique(),
            first=pl.col("event_time").min(),
            last=pl.col("event_time").max(),
            max_step=pl.col("event_time").unique().sort().diff().max(),
        )
        .with_columns(
            missing=((pl.col("last") - pl.col("first")) // bar_ns + 1 - pl.col("bars")),
            largest_gap=(pl.col("max_step").fill_null(bar_ns) // bar_ns - 1).clip(lower_bound=0),
            weekend=pl.col("session").dt.weekday() >= 6,
        )
        .sort(["symbol", "session"])
        .collect()
    )

    symbols: list[dict[str, object]] = []
    totals = dict.fromkeys(_ERROR_COLUMNS, 0)
    for row in base.iter_rows(named=True):
        mine = sessions.filter(pl.col("symbol") == row["symbol"])
        median_bars = float(mine.select(pl.col("bars").median()).item() or 0.0)
        short = mine.filter(pl.col("bars") < SHORT_SESSION_FRACTION * median_bars)
        gappy = mine.filter(pl.col("missing") > 0).sort(
            ["missing", "session"], descending=[True, False]
        )
        weekend = mine.filter(pl.col("weekend"))
        errors = {name: int(row[name]) for name in _ERROR_COLUMNS}
        for name, count in errors.items():
            totals[name] += count
        symbols.append(
            {
                "symbol": row["symbol"],
                "rows": int(row["rows"]),
                "first": _iso(int(row["first"])),
                "last": _iso(int(row["last"])),
                "sessions": mine.height,
                "outside_calendar_bars": int(outside.get(row["symbol"], 0)),
                "errors": errors,
                "zero_volume_bars": int(row["zero_volume_bars"]),
                "missing_minutes": int(mine["missing"].sum()),
                "sessions_with_gaps": gappy.height,
                "largest_gap_minutes": int(mine.select(pl.col("largest_gap").max()).item() or 0),
                "worst_gaps": [
                    {
                        "session": r["session"].isoformat(),
                        "missing": int(r["missing"]),
                        "largest_gap": int(r["largest_gap"]),
                    }
                    for r in gappy.head(top).iter_rows(named=True)
                ],
                "median_bars_per_session": median_bars,
                "short_sessions": short.height,
                "short_session_examples": [
                    {"session": r["session"].isoformat(), "bars": int(r["bars"])}
                    for r in short.sort("bars").head(top).iter_rows(named=True)
                ],
                "weekend_sessions": weekend.height,
                "weekend_session_examples": [
                    {"session": r["session"].isoformat(), "bars": int(r["bars"])}
                    for r in weekend.head(top).iter_rows(named=True)
                ],
            }
        )

    report: dict[str, object] = {
        "report": "integrity",
        "bar_seconds": bar_seconds,
        "session_rule": session,
        "ok": not any(totals.values()),
        "errors": totals,
        "symbols": symbols,
        "calendar": _calendar_check(sessions, calendar, top) if calendar else None,
    }
    return report


def _midnight_ns(day: dt.date) -> TimestampNs:
    return TimestampNs(
        int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * NS_PER_S
    )


def _calendar_check(sessions: pl.DataFrame, name: str, top: int) -> dict[str, object]:
    """Session dates present in the data vs the calendar's, over the data's own date range."""
    data_dates = set(sessions["session"].unique().to_list())
    first, last = min(data_dates), max(data_dates)
    cal: ExchangeCalendarAdapter | AlwaysOpenCalendar = get_trading_calendar(
        name, start=_midnight_ns(first), end=_midnight_ns(last)
    )
    if not isinstance(cal, ExchangeCalendarAdapter):
        msg = f"calendar {name!r} has no session dates to compare; use an exchange_calendars name"
        raise ConfigurationError(msg)
    expected = set(cal.session_dates(first, last))
    only_data = sorted(data_dates - expected)
    only_calendar = sorted(expected - data_dates)
    return {
        "name": name,
        "range": [first.isoformat(), last.isoformat()],
        "data_sessions": len(data_dates),
        "calendar_sessions": len(expected),
        "in_data_not_calendar": len(only_data),
        "in_data_not_calendar_examples": [d.isoformat() for d in only_data[:top]],
        "in_calendar_not_data": len(only_calendar),
        "in_calendar_not_data_examples": [d.isoformat() for d in only_calendar[:top]],
    }
