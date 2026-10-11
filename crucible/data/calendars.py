"""Trading calendars: one equity exchange (via ``exchange_calendars``) and 24/7.

This module and the I/O boundary are the only places timezone logic is
allowed (ADR-0004). Everything returned is UTC int64 ns.
"""

from __future__ import annotations

import bisect
import datetime as dt
import functools

import exchange_calendars as xcals

from crucible.core.errors import ConfigurationError
from crucible.core.types import NS_PER_S, TimestampNs

_DAY_NS = 86_400 * NS_PER_S


def _from_ns(ts: TimestampNs) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts / NS_PER_S, tz=dt.UTC)


_WINDOW_PAD_DAYS = 366


class ExchangeCalendarAdapter:
    """Wraps an ``exchange_calendars`` calendar; satisfies ``TradingCalendar``.

    The calendar covers ``[start - 366 days, end + 366 days]`` (UTC dates), so it depends only
    on the requested range and never on today's date (ADR-0053). Sessions outside that window
    do not exist for this adapter: ``session_closes`` is empty there and
    ``next_session_close`` raises.
    """

    def __init__(self, name: str, *, start: TimestampNs, end: TimestampNs) -> None:
        if int(end) < int(start):
            msg = f"calendar {name}: end={end} is before start={start}; pass a non-empty range"
            raise ConfigurationError(msg)
        pad = dt.timedelta(days=_WINDOW_PAD_DAYS)
        self.name = name
        self.window = (_from_ns(start).date() - pad, _from_ns(end).date() + pad)
        self._cal = _load_calendar(name, self.window)
        self._bounds: tuple[list[int], list[int]] | None = None

    def is_open(self, ts: TimestampNs) -> bool:
        return bool(self._cal.is_open_on_minute(_from_ns(ts)))

    def session_closes(self, start: TimestampNs, end: TimestampNs) -> list[TimestampNs]:
        closes = self._cal.closes
        out: list[TimestampNs] = []
        for close in closes:
            ns = TimestampNs(int(close.timestamp() * NS_PER_S))
            if int(start) <= int(ns) <= int(end):
                out.append(ns)
        return out

    def session_open_by_close(self, start: TimestampNs, end: TimestampNs) -> dict[int, int]:
        """Maps each session close (UTC ns) in [start, end] to that session's
        open. Used by the feed to stamp true ``open_time`` on daily bars."""
        out: dict[int, int] = {}
        for open_ts, close_ts in zip(self._cal.opens, self._cal.closes, strict=True):
            close_ns = int(close_ts.timestamp() * NS_PER_S)
            if int(start) <= close_ns <= int(end):
                out[close_ns] = int(open_ts.timestamp() * NS_PER_S)
        return out

    def session_open_at(self, ts: TimestampNs) -> TimestampNs | None:
        """Open of the session with ``open <= ts <= close`` (UTC ns), else ``None``
        (before an open, in a gap, on a non-session day). ADR-0046."""
        if self._bounds is None:
            self._bounds = (
                [int(open_ts.timestamp() * NS_PER_S) for open_ts in self._cal.opens],
                [int(close_ts.timestamp() * NS_PER_S) for close_ts in self._cal.closes],
            )
        opens, closes = self._bounds
        index = bisect.bisect_right(opens, int(ts)) - 1
        if index >= 0 and int(ts) <= closes[index]:
            return TimestampNs(opens[index])
        return None

    def next_session_close(self, ts: TimestampNs) -> TimestampNs:
        for close in self._cal.closes:
            ns = TimestampNs(int(close.timestamp() * NS_PER_S))
            if int(ns) >= int(ts):
                return ns
        msg = f"no session close at or after ts={ts} within calendar {self.name} bounds"
        raise ValueError(msg)


@functools.lru_cache(maxsize=8)
def _load_calendar(name: str, window: tuple[dt.date, dt.date]) -> xcals.ExchangeCalendar:
    try:
        return xcals.get_calendar(name, start=window[0], end=window[1])
    except Exception as exc:  # exchange_calendars raises several untyped errors
        msg = (
            f"calendar {name!r} cannot cover {window[0]}..{window[1]}: {exc}; check the "
            "calendar name and the start/end dates"
        )
        raise ConfigurationError(msg) from exc


class AlwaysOpenCalendar:
    """24/7 markets (crypto): daily sessions closing at UTC midnight."""

    name = "24/7"

    def is_open(self, ts: TimestampNs) -> bool:
        return True

    def session_closes(self, start: TimestampNs, end: TimestampNs) -> list[TimestampNs]:
        first = -(-int(start) // _DAY_NS) * _DAY_NS  # ceil to next midnight
        return [TimestampNs(t) for t in range(first, int(end) + 1, _DAY_NS)]

    def session_open_at(self, ts: TimestampNs) -> TimestampNs | None:
        """The UTC day ``[D, D+1)`` containing ``ts``: a timestamp exactly at
        midnight is the START of that day, the same reading as a midnight-stamped
        ex-date on an exchange calendar (ADR-0046 amendment)."""
        return TimestampNs(int(ts) // _DAY_NS * _DAY_NS)

    def next_session_close(self, ts: TimestampNs) -> TimestampNs:
        return TimestampNs(-(-int(ts) // _DAY_NS) * _DAY_NS)

    def session_open_by_close(self, start: TimestampNs, end: TimestampNs) -> dict[int, int]:
        """24/7 daily sessions open exactly one day before they close."""
        return {int(close): int(close) - _DAY_NS for close in self.session_closes(start, end)}


ALWAYS_OPEN = "24/7"


def canonical_calendar(name: str) -> str:
    """The one name for a set of trading sessions (ADR-0071): ``"24/7"`` for the always-open
    market, otherwise the ``exchange_calendars`` code after upper-casing and alias resolution, so
    ``"nyse"``, ``"NYSE"`` and ``"XNYS"`` (and ``"XNAS"``, which ``exchange_calendars`` maps to the
    same sessions) are one calendar. Refuses a name ``exchange_calendars`` does not know."""
    text = name.strip()
    if text == ALWAYS_OPEN:
        return ALWAYS_OPEN
    try:
        resolved = str(xcals.resolve_alias(text.upper()))
    except Exception:  # exchange_calendars raises its own untyped InvalidCalendarName
        resolved = ""
    if resolved not in xcals.get_calendar_names(include_aliases=False):
        msg = (
            f"unknown trading calendar {name!r}; use '24/7' or an exchange_calendars code such "
            "as XNYS (New York), XLON (London) or XTKS (Tokyo)"
        )
        raise ConfigurationError(msg)
    return resolved


def get_trading_calendar(
    name: str, *, start: TimestampNs, end: TimestampNs
) -> ExchangeCalendarAdapter | AlwaysOpenCalendar:
    """Calendar factory used by config. ``'24/7'`` is the always-open market.

    ``start``/``end`` (UTC ns) are the range the caller works on; an exchange calendar is built
    over that range padded by a year (ADR-0053). They are required so nothing falls back to
    ``exchange_calendars``' date-dependent default window.
    """
    if name == "24/7":
        return AlwaysOpenCalendar()
    return ExchangeCalendarAdapter(name, start=start, end=end)
