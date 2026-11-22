"""Scheduled economic events as the prop engine sees them (ADR-0107 section 12).

This module is deliberately tiny and imports nothing from the data layer: the calendar is built
and versioned by the ingestion path (``docs/data/econ-events.md``), and a ``NewsEvent`` is the
only row the rule engine needs — an id, a type and the scheduled publication instant in UTC
nanoseconds. A news rule with no events, or an attempt whose window the calendar does not cover,
is ``not_modeled`` for that attempt and reported, never silently treated as no news.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass

_NS_PER_S = 1_000_000_000


@dataclass(frozen=True, slots=True)
class NewsEvent:
    """One scheduled publication. ``scheduled_ns`` is UTC nanoseconds, the instant it is known.

    ``time_known`` is REQUIRED and is the source's own claim: ``False`` means the calendar gives
    the release DATE but not the time (some official statements only say "for immediate
    release"). Such an event NEVER gets a window at an invented time: its whole trade date is
    outside news coverage, so the news rule is ``not_modeled`` for that day and the gap names the
    event id. Treating it as "no news" would be an unrestricted window the source does not
    support.
    """

    event_id: str
    event_type: str
    scheduled_ns: int
    time_known: bool

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_type:
            msg = "a news event needs a non-empty event_id and event_type"
            raise ValueError(msg)
        if self.scheduled_ns % _NS_PER_S != 0:
            msg = (
                "news event scheduled_ns must be a whole second in UTC nanoseconds; a scheduled "
                "instant is never a float"
            )
            raise ValueError(msg)


Coverage = tuple[tuple[int, int], ...]


def coverage_covers(coverage: Coverage | None, start_ns: int, end_ns: int) -> bool:
    """Whether the calendar covers the whole ``[start_ns, end_ns]`` attempt period.

    No coverage at all means the period is uncovered: a material ``not_modeled`` gap.
    """
    if not coverage:
        return False
    return any(low <= start_ns and end_ns <= high for low, high in coverage)


def events_in_window(
    events: Iterable[NewsEvent],
    event_types: Iterable[str],
    start_ns: int,
    end_ns: int,
) -> list[NewsEvent]:
    """The timed events of the declared types whose scheduled instant lies in the window.

    An event whose ``time_known`` is false is never returned: it has no instant to build a window
    around, and it is reported as an uncovered day instead.
    """
    wanted = set(event_types)
    return sorted(
        (
            event
            for event in events
            if event.event_type in wanted
            and event.time_known
            and start_ns <= event.scheduled_ns <= end_ns
        ),
        key=lambda event: (event.scheduled_ns, event.event_id),
    )


def _trade_date_bounds_ns(event: NewsEvent) -> tuple[int, int]:
    """``[midnight_utc, next_midnight_utc)`` of the event's date, in nanoseconds."""
    day = dt.datetime.fromtimestamp(event.scheduled_ns // _NS_PER_S, dt.UTC).date()
    start = int(dt.datetime.combine(day, dt.time(0, 0), tzinfo=dt.UTC).timestamp()) * _NS_PER_S
    return start, start + 24 * 60 * 60 * _NS_PER_S


def unknown_time_gaps(events: Iterable[NewsEvent], start_ns: int, end_ns: int) -> tuple[str, ...]:
    """Event ids whose date lies in ``[start_ns, end_ns]`` but whose release time is unknown.

    Their whole trade date is outside news coverage: the caller must report it and treat the
    news rule as ``not_modeled``, never as an unrestricted window.
    """
    gaps: list[str] = []
    for event in events:
        if event.time_known:
            continue
        low, high = _trade_date_bounds_ns(event)
        if low <= end_ns and start_ns <= high:
            gaps.append(event.event_id)
    return tuple(sorted(gaps))


def minute_ns(minutes: int) -> int:
    return int(minutes) * 60 * _NS_PER_S


def to_ns(instant: dt.datetime) -> int:
    """UTC nanoseconds of an aware datetime (the one place a timezone enters this package)."""
    if instant.tzinfo is None:
        msg = "a news instant must be timezone-aware"
        raise ValueError(msg)
    return int(instant.timestamp()) * _NS_PER_S
