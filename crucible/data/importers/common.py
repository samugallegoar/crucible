"""Pieces shared by every bar importer: the exchange session-close lookup and the OHLC bound
check/clamp (ADR-0052, ADR-0063). Pure functions; nothing here reads a file or the network."""

from __future__ import annotations

import datetime as dt

import exchange_calendars as xcals
import polars as pl

from crucible.core.errors import ConfigurationError

NS_PER_S = 1_000_000_000


def session_close_table(first: dt.date, last: dt.date, calendar_name: str) -> pl.DataFrame:
    """``day`` (Date) and ``close_ns`` (UTC ns) of every session close of ``calendar_name`` over
    ``[first, last]``. The calendar is built for that range (padded a week): the library's default
    window moves with today's date and would drop old real sessions as "not_a_session"."""
    try:
        calendar = xcals.get_calendar(
            calendar_name, start=first - dt.timedelta(days=7), end=last + dt.timedelta(days=7)
        )
    except Exception as exc:  # exchange_calendars raises several untyped errors
        msg = (
            f"calendar {calendar_name!r} cannot cover {first}..{last}: {exc}; check the "
            "calendar name and the dates in the file"
        )
        raise ConfigurationError(msg) from exc
    by_date = {
        session.date(): int(close.timestamp()) * NS_PER_S
        for session, close in zip(calendar.closes.index, calendar.closes, strict=True)
    }
    return pl.DataFrame(
        {"day": list(by_date), "close_ns": list(by_date.values())},
        schema={"day": pl.Date, "close_ns": pl.Int64},
    )


def ohlc_violation() -> pl.Expr:
    """True where a bar breaks ``low <= min(open, close) <= max(open, close) <= high``."""
    return (
        (pl.col("low") > pl.min_horizontal("open", "close"))
        | (pl.col("high") < pl.max_horizontal("open", "close"))
        | (pl.col("low") > pl.col("high"))
    )


def clamp_ohlc(frame: pl.DataFrame, violation: pl.Expr) -> pl.DataFrame:
    """Widens ``high``/``low`` of the violating rows to cover all four prices."""
    return frame.with_columns(
        high=pl.when(violation)
        .then(pl.max_horizontal("open", "high", "low", "close"))
        .otherwise(pl.col("high")),
        low=pl.when(violation)
        .then(pl.min_horizontal("open", "high", "low", "close"))
        .otherwise(pl.col("low")),
    )
