"""CME Globex session calendar for the equity-index futures (Fathom C3b, ADR-0091).

The scheduled trading segments of every Globex trade date, built from a versioned table
(``cme_session_table``) of published CME schedules, never from observed bars:

- a *regime* gives the regular week of a period: when a trade date's session opens on the
  previous calendar day (Monday's on Sunday at 17:00), when it closes, and the daily closed
  windows (maintenance, the 15:15-15:30 halt of 2012-2021);
- an *override* replaces the open, the close or adds halts on one trade date (holidays, early
  closes, the special closures of 2012, 2018 and 2025), each with its source document;
- a *no-trade-date* removes a weekday (Good Friday, Christmas, ...);
- an *unsourced window* marks calendar days whose schedule no source covers: the sessions that
  touch it are built from the regime but flagged ``verified=False``, and strict users refuse them.

Missing bars do not prove a market was closed and extra bars are not a schedule: observed bars
only validate the table (``schedule_report``). All times in the table are ``America/Chicago``
wall clock; this module converts them to UTC int64 nanoseconds through ``calendars`` and works in
UTC from there. Timing: the schedule of a trade date is published before it (holiday calendars
months ahead, special closures days ahead), so using it at decision time is not look-ahead; the
one after-the-fact record (the 2025-11-28 outage) is informational and never changes a session.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.data.calendars import chicago_wall_to_utc_ns, utc_ns_to_chicago_wall

_NS_PER_S = 1_000_000_000
_SUNDAY_OPEN = dt.time(17, 0)


@dataclass(frozen=True, slots=True)
class ScheduleSource:
    """A document the table was transcribed from. ``sha256`` is of the bytes retrieved (None for
    a web page read as text); ``archive_url`` the Wayback copy actually read when CME's own site
    refused automated access."""

    key: str
    title: str
    publisher: str
    url: str
    retrieved: str
    published: str | None = None
    archive_url: str | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class SessionRegime:
    """The regular week of a period, for the roots listed. A weekday trade date ``D`` opens at
    ``open_previous_day`` on ``D - 1`` (Monday: Sunday 17:00) and closes at ``close`` on ``D``;
    ``breaks`` are daily closed windows ``[start, end)`` applied to every calendar day the session
    spans."""

    name: str
    roots: frozenset[str]
    first_trade_date: dt.date
    last_trade_date: dt.date | None
    open_previous_day: dt.time
    close: dt.time
    breaks: tuple[tuple[dt.time, dt.time], ...]
    sources: tuple[str, ...]

    def applies(self, root: str, day: dt.date) -> bool:
        return (
            root in self.roots
            and day >= self.first_trade_date
            and (self.last_trade_date is None or day <= self.last_trade_date)
        )


@dataclass(frozen=True, slots=True)
class SessionOverride:
    """One trade date that differs from its regime: a new ``open``/``close`` (wall clock) and/or
    extra ``halts`` ``[start, end)``. ``kind`` is ``holiday`` (published holiday calendar) or
    ``special`` (a closure announced days ahead: Hurricane Sandy, national days of mourning)."""

    trade_date: dt.date
    roots: frozenset[str]
    source: str
    kind: Literal["holiday", "special"]
    note: str
    open: dt.datetime | None = None
    close: dt.datetime | None = None
    halts: tuple[tuple[dt.datetime, dt.datetime], ...] = ()


@dataclass(frozen=True, slots=True)
class NoTradeDate:
    """A weekday with no trade date of its own (the exchange is closed, or its trading belongs to
    the next trade date)."""

    date: dt.date
    roots: frozenset[str]
    source: str
    note: str


@dataclass(frozen=True, slots=True)
class UnsourcedWindow:
    """Calendar days ``[first, last]`` whose schedule no transcribed source covers."""

    first: dt.date
    last: dt.date
    roots: frozenset[str]
    reason: str


@dataclass(frozen=True, slots=True)
class UnscheduledEvent:
    """An interruption recorded after the fact (an outage). Informational: a decision could not
    have known it, so it never changes a session; the missing bars it leaves are data gaps."""

    trade_date: dt.date
    roots: frozenset[str]
    source: str
    note: str


@dataclass(frozen=True, slots=True)
class SessionTable:
    """The whole versioned table (see ``cme_session_table``)."""

    version: str
    retrieved: str
    coverage: dict[str, tuple[dt.date, dt.date]]
    regimes: tuple[SessionRegime, ...]
    overrides: tuple[SessionOverride, ...]
    no_trade_dates: tuple[NoTradeDate, ...]
    unsourced: tuple[UnsourcedWindow, ...]
    unscheduled: tuple[UnscheduledEvent, ...]
    sources: tuple[ScheduleSource, ...]
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TradeDateSession:
    """The scheduled trading of one trade date of one root: ``segments`` are disjoint, sorted
    ``[start_ns, end_ns)`` UTC intervals. ``verified`` is False when an unsourced window touches
    the session (its times are the regime's, unconfirmed)."""

    root: str
    trade_date: dt.date
    segments: tuple[tuple[int, int], ...]
    verified: bool
    regime: str
    sources: tuple[str, ...]
    notes: tuple[str, ...] = field(default=())

    @property
    def open_ns(self) -> int:
        return self.segments[0][0]

    @property
    def close_ns(self) -> int:
        return self.segments[-1][1]

    def bar_ends(self, bar_seconds: int = 60) -> list[int]:
        """End timestamps of the scheduled bars: every ``bar_seconds`` bar lying wholly inside a
        segment, labelled by its end (the data convention)."""
        step = bar_seconds * _NS_PER_S
        ends: list[int] = []
        for start, end in self.segments:
            ends.extend(range(start + step, end + 1, step))
        return ends


def _key(roots: frozenset[str], root: str) -> bool:
    return root in roots


def _combine(day: dt.date, clock: dt.time) -> dt.datetime:
    return dt.datetime.combine(day, clock)


def _subtract(
    span: list[tuple[dt.datetime, dt.datetime]], cut: tuple[dt.datetime, dt.datetime]
) -> list[tuple[dt.datetime, dt.datetime]]:
    out: list[tuple[dt.datetime, dt.datetime]] = []
    a, b = cut
    for s, e in span:
        if b <= s or a >= e:
            out.append((s, e))
            continue
        if s < a:
            out.append((s, a))
        if b < e:
            out.append((b, e))
    return out


class SessionCalendar:
    """Sessions of one root from a ``SessionTable``. Refuses a trade date outside the root's
    coverage and a table whose entries contradict each other (overlapping sessions, a session
    after a closed weekday without an explicit open)."""

    def __init__(self, table: SessionTable, root: str) -> None:
        root = root.upper()
        if root not in table.coverage:
            msg = (
                f"the CME session calendar {table.version} has no schedule for root {root!r}; "
                f"covered roots: {sorted(table.coverage)}"
            )
            raise ConfigurationError(msg)
        self.table = table
        self.root = root
        self.first, self.last = table.coverage[root]
        self._overrides = {o.trade_date: o for o in table.overrides if _key(o.roots, root)}
        self._closed = {n.date: n for n in table.no_trade_dates if _key(n.roots, root)}
        self._unsourced = [u for u in table.unsourced if _key(u.roots, root)]
        self._regimes = [r for r in table.regimes if root in r.roots]

    def _regime(self, day: dt.date) -> SessionRegime:
        found = [r for r in self._regimes if r.applies(self.root, day)]
        if len(found) != 1:
            msg = (
                f"{self.root} trade date {day}: {len(found)} session regimes apply (table "
                f"{self.table.version}); the table must give exactly one"
            )
            raise DataQualityError(msg)
        return found[0]

    def is_trade_date(self, day: dt.date) -> bool:
        return day.weekday() < 5 and day not in self._closed

    def _wall_span(
        self, day: dt.date
    ) -> tuple[
        SessionRegime, list[tuple[dt.datetime, dt.datetime]], tuple[str, ...], tuple[str, ...]
    ]:
        regime = self._regime(day)
        override = self._overrides.get(day)
        if day.weekday() == 0:
            default_open = _combine(day - dt.timedelta(days=1), _SUNDAY_OPEN)
        else:
            default_open = _combine(day - dt.timedelta(days=1), regime.open_previous_day)
        previous = day - dt.timedelta(days=1)
        if (
            previous.weekday() < 5
            and previous in self._closed
            and (override is None or override.open is None)
        ):
            msg = (
                f"{self.root} trade date {day} follows the closed weekday {previous} but the "
                f"table {self.table.version} gives no explicit open for it; transcribe the open "
                "from the holiday schedule instead of assuming the regular one"
            )
            raise DataQualityError(msg)
        opened = (
            override.open if override is not None and override.open is not None else default_open
        )
        closed = (
            override.close
            if override is not None and override.close is not None
            else _combine(day, regime.close)
        )
        if closed <= opened:
            msg = f"{self.root} trade date {day}: close {closed} is not after open {opened}"
            raise DataQualityError(msg)
        span = [(opened, closed)]
        cursor = opened.date()
        while cursor <= closed.date():
            for start, end in regime.breaks:
                span = _subtract(span, (_combine(cursor, start), _combine(cursor, end)))
            cursor += dt.timedelta(days=1)
        sources = regime.sources
        notes: tuple[str, ...] = ()
        if override is not None:
            for halt in override.halts:
                span = _subtract(span, halt)
            sources = (*sources, override.source)
            notes = (f"{override.kind}: {override.note}",)
        span = [(s, e) for s, e in span if e > s]
        if not span:
            msg = f"{self.root} trade date {day}: the table leaves no trading time"
            raise DataQualityError(msg)
        return regime, span, sources, notes

    def session(self, day: dt.date) -> TradeDateSession:
        """The session of trade date ``day``. Refuses a weekend, a no-trade-date weekday and a date
        outside the root's coverage."""
        if not self.first <= day <= self.last:
            msg = (
                f"{self.root} trade date {day} is outside the CME session calendar "
                f"{self.table.version} coverage [{self.first}, {self.last}]"
            )
            raise ConfigurationError(msg)
        if not self.is_trade_date(day):
            msg = f"{day} is not a {self.root} Globex trade date"
            raise ConfigurationError(msg)
        return self.sessions(day, day)[0]

    def sessions(self, first: dt.date, last: dt.date) -> list[TradeDateSession]:
        """Every trade date in ``[first, last]`` (clipped to nothing outside coverage: a range
        reaching outside it is refused)."""
        if first < self.first or last > self.last:
            msg = (
                f"{self.root} sessions [{first}, {last}] reach outside the CME session calendar "
                f"{self.table.version} coverage [{self.first}, {self.last}]"
            )
            raise ConfigurationError(msg)
        days: list[dt.date] = []
        cursor = first
        while cursor <= last:
            if self.is_trade_date(cursor):
                days.append(cursor)
            cursor += dt.timedelta(days=1)
        built = [self._wall_span(d) for d in days]
        walls = [t for _, span, _, _ in built for seg in span for t in seg]
        utc = chicago_wall_to_utc_ns(walls)
        out: list[TradeDateSession] = []
        i = 0
        for day, (regime, span, sources, notes) in zip(days, built, strict=True):
            segments = []
            for _ in span:
                segments.append((utc[i], utc[i + 1]))
                i += 2
            lo, hi = span[0][0].date(), span[-1][1].date()
            verified = not any(u.first <= hi and lo <= u.last for u in self._unsourced)
            out.append(
                TradeDateSession(
                    root=self.root,
                    trade_date=day,
                    segments=tuple(segments),
                    verified=verified,
                    regime=regime.name,
                    sources=tuple(dict.fromkeys(sources)),
                    notes=notes,
                )
            )
        for a, b in itertools.pairwise(out):
            if b.open_ns < a.close_ns:
                msg = (
                    f"{self.root}: the sessions of {a.trade_date} and {b.trade_date} overlap in "
                    f"table {self.table.version}"
                )
                raise DataQualityError(msg)
        return out


# --- assignment of bars to sessions -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarSchedule:
    """Each bar's place in the schedule. ``session_index`` is the index into ``sessions`` of the
    session whose segment holds the whole bar, -1 when none does (an off-schedule bar)."""

    sessions: tuple[TradeDateSession, ...]
    session_index: NDArray[np.int64]

    @property
    def on_schedule(self) -> NDArray[np.bool_]:
        return np.asarray(self.session_index >= 0)


def assign_bars(
    calendar: SessionCalendar, bar_ends: NDArray[np.int64], bar_seconds: int = 60
) -> BarSchedule:
    """Place bars (labelled by their END, UTC ns) in the scheduled sessions. A bar belongs to a
    session when ``[end - bar_seconds, end)`` lies inside one of its segments."""
    ends = np.asarray(bar_ends, dtype=np.int64)
    if ends.size == 0:
        return BarSchedule(sessions=(), session_index=np.zeros(0, dtype=np.int64))
    step = bar_seconds * _NS_PER_S
    first_wall = utc_ns_to_chicago_wall([int(ends.min() - step)])[0]
    last_wall = utc_ns_to_chicago_wall([int(ends.max())])[0]
    # a session opens up to four days before its trade date (Monday's on the Thursday of a
    # Friday holiday) and an off-schedule print needs the session that opened before it, so load
    # a week on both sides
    first = max(calendar.first, first_wall.date() - dt.timedelta(days=7))
    last = min(calendar.last, last_wall.date() + dt.timedelta(days=7))
    span_open, span_close = coverage_span(calendar)
    if int(ends.min()) - step < span_open or int(ends.max()) > span_close:
        msg = (
            f"{calendar.root} bars run from {first_wall:%Y-%m-%d %H:%M} to "
            f"{last_wall:%Y-%m-%d %H:%M} Chicago, outside the CME session calendar "
            f"{calendar.table.version} coverage [{calendar.first}, {calendar.last}]"
        )
        raise ConfigurationError(msg)
    sessions = calendar.sessions(first, last)
    starts: list[int] = []
    stops: list[int] = []
    owner: list[int] = []
    for k, s in enumerate(sessions):
        for a, b in s.segments:
            starts.append(a)
            stops.append(b)
            owner.append(k)
    seg_start = np.asarray(starts, dtype=np.int64)
    seg_stop = np.asarray(stops, dtype=np.int64)
    seg_owner = np.asarray(owner, dtype=np.int64)
    pos = np.searchsorted(seg_start, ends - step, side="right") - 1
    valid = pos >= 0
    safe = np.where(valid, pos, 0)
    inside = valid & (ends - step >= seg_start[safe]) & (ends <= seg_stop[safe])
    index = np.where(inside, seg_owner[safe], -1).astype(np.int64)
    return BarSchedule(sessions=tuple(sessions), session_index=index)


def trade_date_of(
    calendar: SessionCalendar, bar_ends: NDArray[np.int64], bar_seconds: int = 60
) -> list[dt.date | None]:
    """The Globex trade date of each bar (by its end), None for an off-schedule bar."""
    placed = assign_bars(calendar, bar_ends, bar_seconds)
    return [placed.sessions[i].trade_date if i >= 0 else None for i in placed.session_index]


def coverage_span(calendar: SessionCalendar) -> tuple[int, int]:
    """``(open, close)`` UTC ns of the first and last covered sessions of ``calendar``: a bar
    ``[end - bar_seconds, end)`` can be placed only when it lies within this span."""
    head = calendar.sessions(calendar.first, min(calendar.last, calendar.first + dt.timedelta(6)))
    tail = calendar.sessions(max(calendar.first, calendar.last - dt.timedelta(6)), calendar.last)
    return head[0].open_ns, tail[-1].close_ns


def session_trade_dates(
    calendar: SessionCalendar, bar_ends: NDArray[np.int64], bar_seconds: int = 60
) -> tuple[NDArray[np.datetime64], NDArray[np.bool_]]:
    """The Globex trade date of every bar (by its end, UTC ns) and whether it is on schedule.

    A bar inside a scheduled segment takes that session's trade date. An off-schedule bar (the
    print in the minute after a close, or the one ending exactly at a reopen) takes the trade
    date of the last session that opened at or before the bar's start: it is kept, never moved
    forward in time, and its ``on_schedule`` is False so that execution refuses to trade on it
    (ADR-0091, decision 7). Refuses bars outside the calendar's coverage (``assign_bars``).
    Timing: the schedule is published in advance, so this uses no data after the bar.
    """
    ends = np.asarray(bar_ends, dtype=np.int64)
    placed = assign_bars(calendar, ends, bar_seconds)
    if ends.size == 0:
        return np.zeros(0, dtype="datetime64[D]"), np.zeros(0, dtype=np.bool_)
    opens = np.asarray([s.open_ns for s in placed.sessions], dtype=np.int64)
    days = np.asarray([s.trade_date for s in placed.sessions], dtype="datetime64[D]")
    before = np.searchsorted(opens, ends - bar_seconds * _NS_PER_S, side="right") - 1
    index = np.where(placed.session_index >= 0, placed.session_index, before)
    if (index < 0).any():  # unreachable after the coverage check; kept as a hard guard
        msg = f"{calendar.root}: a bar precedes every session of the CME calendar"
        raise DataQualityError(msg)
    return days[index], placed.on_schedule


# --- session rules on the trade-date clock -----------------------------------------------------


def _clock(text: str, what: str) -> dt.time:
    try:
        hours, minutes = text.split(":")
        return dt.time(int(hours), int(minutes))
    except ValueError as exc:
        msg = f"{what}: {text!r} is not an HH:MM clock time"
        raise ConfigurationError(msg) from exc


def trade_date_instant(calendar: SessionCalendar, session: TradeDateSession, clock: str) -> int:
    """UTC ns of wall clock ``clock`` on the TRADE-DATE clock of ``session``: a time at or after
    the regime's evening open (17:00; 15:30 before 2012-11-19) is on the calendar day before the
    trade date, any earlier time on the trade date itself. So ``18:00`` is the evening that opens
    trade date ``D`` and ``15:50`` is the afternoon of ``D``, whatever calendar day a bar falls
    on."""
    regime = calendar._regime(session.trade_date)
    wall = _clock(clock, "session clock")
    day = (
        session.trade_date - dt.timedelta(days=1)
        if wall >= regime.open_previous_day
        else session.trade_date
    )
    return chicago_wall_to_utc_ns([_combine(day, wall)])[0]


@dataclass(frozen=True, slots=True)
class SessionRuleMasks:
    """Per-bar session facts for the futures path. ``on_schedule``: the bar lies inside a
    scheduled segment; an off-schedule bar (a print in the minute after a close, before a reopen)
    is not tradable: nothing is decided at its close and nothing fills at its open, and it never
    forces a position flat. ``force_flat``: the target must be 0 from this bar's close on;
    ``entry_ok``: a new position may be opened at this bar's close. ``missing_final``: trade dates
    whose final scheduled bar is absent from the data, so a flat-by-close exit cannot fill inside
    the session; ``unverified``: trade dates touching an unsourced window; ``off_schedule``: the
    count of off-schedule bars."""

    trade_date: list[dt.date | None]
    on_schedule: NDArray[np.bool_]
    force_flat: NDArray[np.bool_]
    entry_ok: NDArray[np.bool_]
    missing_final: tuple[dt.date, ...]
    unverified: tuple[dt.date, ...]
    off_schedule: int


def session_rule_masks(
    calendar: SessionCalendar,
    bar_ends: NDArray[np.int64],
    *,
    bar_seconds: int = 60,
    flat_by_close: bool = False,
    exit_at: str | None = None,
    entry_window: tuple[str, str] | None = None,
) -> SessionRuleMasks:
    """Evaluate the session rules on the scheduled sessions.

    - ``flat_by_close``: the exit is decided at the close of the session's PENULTIMATE scheduled
      bar and fills at the open of the FINAL scheduled bar (next-bar-open timing). Bars from the
      penultimate one on are flat and closed to entries. When the penultimate bar is missing from
      the data, the last observed bar before it decides instead (earlier, never later). When the
      final scheduled bar is missing the exit cannot fill inside the session: the trade date is
      listed in ``missing_final`` and a strict run refuses rather than fill at another bar.
    - ``exit_at``: flat from the first bar ending at or after the trade-date instant
      (``trade_date_instant``) and no entry after it; on a session that closes before that instant
      (an early close) the flat-by-close rule applies instead.
    - ``entry_window``: entries only on bars ending inside ``[start, end]`` on the trade-date
      clock (``("18:00", "10:00")`` spans midnight naturally).
    Off-schedule bars are closed to entries and never force a position flat (``on_schedule``).
    """
    ends = np.asarray(bar_ends, dtype=np.int64)
    placed = assign_bars(calendar, ends, bar_seconds)
    n = ends.size
    force_flat = np.zeros(n, dtype=np.bool_)
    entry_ok = placed.on_schedule.copy()
    step = bar_seconds * _NS_PER_S
    missing_final: list[dt.date] = []
    by_session: dict[int, NDArray[np.int64]] = {}
    if n:
        order = np.flatnonzero(placed.session_index >= 0)
        for k in np.unique(placed.session_index[order]):
            by_session[int(k)] = order[placed.session_index[order] == k]

    def flat_from(rows: NDArray[np.int64], instant: int) -> None:
        hit = rows[ends[rows] >= instant]
        force_flat[hit] = True
        entry_ok[hit] = False

    for k, rows in by_session.items():
        session = placed.sessions[k]
        scheduled = session.bar_ends(bar_seconds)
        close_rule = flat_by_close
        if exit_at is not None:
            instant = trade_date_instant(calendar, session, exit_at)
            if instant > session.close_ns - step:
                close_rule = True
            else:
                flat_from(rows, instant)
        if close_rule:
            if len(scheduled) < 2:
                msg = (
                    f"{calendar.root} trade date {session.trade_date} has fewer than two scheduled "
                    "bars; a flat-by-close exit has no bar to decide on"
                )
                raise ConfigurationError(msg)
            penultimate, final = scheduled[-2], scheduled[-1]
            observed = ends[rows]
            if not np.any(observed == penultimate):
                earlier = rows[observed < penultimate]
                if earlier.size:
                    force_flat[earlier[-1]] = True
                    entry_ok[earlier[-1]] = False
            flat_from(rows, penultimate)
            if not np.any(observed == final):
                missing_final.append(session.trade_date)
        if entry_window is not None:
            start = trade_date_instant(calendar, session, entry_window[0])
            stop = trade_date_instant(calendar, session, entry_window[1])
            if stop < start:
                msg = (
                    f"session.entry_window {entry_window} ends before it starts on the trade-date "
                    "clock (times from the evening open belong to the evening before)"
                )
                raise ConfigurationError(msg)
            outside = rows[(ends[rows] < start) | (ends[rows] > stop)]
            entry_ok[outside] = False
    entry_ok &= ~force_flat
    dates = [placed.sessions[i].trade_date if i >= 0 else None for i in placed.session_index]
    unverified = tuple(
        sorted(
            {placed.sessions[k].trade_date for k in by_session if not placed.sessions[k].verified}
        )
    )
    return SessionRuleMasks(
        trade_date=dates,
        on_schedule=np.asarray(placed.on_schedule, dtype=np.bool_),
        force_flat=np.asarray(force_flat, dtype=np.bool_),
        entry_ok=np.asarray(entry_ok, dtype=np.bool_),
        missing_final=tuple(missing_final),
        unverified=unverified,
        off_schedule=int(np.count_nonzero(~placed.on_schedule)),
    )


# --- validation against observed bars ----------------------------------------------------------


def schedule_report(
    calendar: SessionCalendar, bar_ends: NDArray[np.int64], *, bar_seconds: int = 60, top: int = 10
) -> dict[str, object]:
    """Observed bars against the schedule. ``off_schedule``: bars outside every segment (a table
    error or a data defect, by trade date); ``gaps``: scheduled bars with no data (data gaps,
    never evidence of a closure). Never changes the table."""
    ends = np.unique(np.asarray(bar_ends, dtype=np.int64))
    placed = assign_bars(calendar, ends, bar_seconds)
    off = ends[~placed.on_schedule]
    off_days: dict[str, int] = {}
    for wall in utc_ns_to_chicago_wall([int(v) for v in off]):
        key = wall.date().isoformat()
        off_days[key] = off_days.get(key, 0) + 1
    observed = set(ends.tolist())
    gaps: list[tuple[str, int, int]] = []
    first_bar = int(ends.min()) if ends.size else 0
    last_bar = int(ends.max()) if ends.size else 0
    for s in placed.sessions:
        scheduled = [b for b in s.bar_ends(bar_seconds) if first_bar <= b <= last_bar]
        if not scheduled:
            continue
        missing = sum(1 for b in scheduled if b not in observed)
        if missing:
            gaps.append((s.trade_date.isoformat(), missing, len(scheduled)))
    gaps.sort(key=lambda g: (-g[1], g[0]))
    return {
        "root": calendar.root,
        "table": calendar.table.version,
        "bars": int(ends.size),
        "off_schedule_bars": int(off.size),
        "off_schedule_days": dict(sorted(off_days.items(), key=lambda kv: (-kv[1], kv[0]))[:top]),
        "off_schedule_day_count": len(off_days),
        "sessions": len(placed.sessions),
        "sessions_with_gaps": len(gaps),
        "missing_scheduled_bars": sum(g[1] for g in gaps),
        "largest_gaps": [{"trade_date": d, "missing": m, "scheduled": t} for d, m, t in gaps[:top]],
        "unverified_sessions": sum(1 for s in placed.sessions if not s.verified),
    }


# --- provenance ---------------------------------------------------------------------------------


def _iso(value: object) -> object:
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dt.time):
        return value.strftime("%H:%M")
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, tuple | list):
        return [_iso(v) for v in value]
    return value


def table_document(table: SessionTable) -> dict[str, object]:
    """The table as plain JSON-ready data (the thing hashed)."""

    def rows(items: tuple[object, ...]) -> list[dict[str, object]]:
        return [
            {name: _iso(getattr(item, name)) for name in item.__slots__}  # type: ignore[attr-defined]
            for item in items
        ]

    return {
        "version": table.version,
        "retrieved": table.retrieved,
        "coverage": {
            k: [a.isoformat(), b.isoformat()] for k, (a, b) in sorted(table.coverage.items())
        },
        "regimes": rows(table.regimes),
        "overrides": rows(table.overrides),
        "no_trade_dates": rows(table.no_trade_dates),
        "unsourced": rows(table.unsourced),
        "unscheduled": rows(table.unscheduled),
        "sources": rows(table.sources),
        "conflicts": list(table.conflicts),
    }


def table_hash(table: SessionTable) -> str:
    """SHA-256 of the canonical JSON of ``table_document``."""
    text = json.dumps(table_document(table), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def table_summary(table: SessionTable) -> dict[str, object]:
    """Version, hash and coverage: what a run manifest records."""
    return {
        "version": table.version,
        "sha256": table_hash(table),
        "retrieved": table.retrieved,
        "coverage": {
            k: [a.isoformat(), b.isoformat()] for k, (a, b) in sorted(table.coverage.items())
        },
    }


__all__ = [
    "BarSchedule",
    "NoTradeDate",
    "ScheduleSource",
    "SessionCalendar",
    "SessionOverride",
    "SessionRegime",
    "SessionRuleMasks",
    "SessionTable",
    "TradeDateSession",
    "UnscheduledEvent",
    "UnsourcedWindow",
    "assign_bars",
    "coverage_span",
    "schedule_report",
    "session_rule_masks",
    "session_trade_dates",
    "table_document",
    "table_hash",
    "table_summary",
    "trade_date_instant",
    "trade_date_of",
]
