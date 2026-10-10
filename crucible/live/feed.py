"""Feed plumbing between the engine and a ``DataFeed`` (ADR-0039).

``FeedContext`` is what the engine hands a feed factory: the data location,
the run window, and the engine's own id/seq callables (the engine owns the
counters, and event ids reach the golden artifacts, so a feed must stamp
through them). ``PeekableFeed`` gives the run loop one event of lookahead and
enforces invariant I9 over the feed: it never sorts or repairs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from crucible.core.errors import CrucibleError, InvariantViolation

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from crucible.core.engine import TradingCalendarLike
    from crucible.core.interfaces import Event
    from crucible.core.types import DatasetId, EventId, TimestampNs
    from crucible.data.store import ParquetDataStore


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedContext:
    """Everything a feed factory needs to build a feed for one engine run.

    ``next_event_id``/``next_seq`` are the engine's counters. A feed must call
    them once per event it creates, in the order it yields them. A feed must
    stamp every event inside ``events()``, before the run starts: the engine's
    feed-first merge equals global ``(ts, seq)`` order only then, and lazy
    stamping is the venue feed's job (ADR-0039).
    """

    store: ParquetDataStore
    bars_dataset: DatasetId
    corporate_actions_dataset: DatasetId | None
    start: TimestampNs
    end: TimestampNs
    calendar: TradingCalendarLike | None
    next_event_id: Callable[[], EventId]
    next_seq: Callable[[], int]


class PeekableFeed:
    """One-event lookahead over ``DataFeed.events()``.

    Timing: ``peek_ts`` reads only the next event's timestamp; the peeked
    event is never handed to the strategy or the PIT accessor, so the peek
    cannot leak information (the strategy still sees an event only when the
    engine pops it at that event's ``ts``).

    Invariant I9: events must arrive with non-decreasing ``ts`` and, at equal
    ``ts``, strictly increasing ``seq``. A violation raises
    ``InvariantViolation`` naming both events.
    """

    def __init__(self, events: Iterator[Event]) -> None:
        self._events = events
        self._head: Event | None = None
        self._last_key: tuple[int, int, str] | None = None
        self._exhausted = False

    @property
    def last_key(self) -> tuple[int, int, str] | None:
        """``(ts, seq, id)`` of the last event popped (``None`` before any)."""
        return self._last_key

    def preload(self, head: Event | None, last_key: tuple[int, int, str] | None) -> None:
        """Restores a checkpointed head event and ordering watermark (resume
        for a lazily stamping feed, ADR-0044). Only legal on a fresh wrapper."""
        if self._head is not None or self._last_key is not None or self._exhausted:
            msg = "preload() needs a fresh PeekableFeed (nothing peeked or popped yet)"
            raise CrucibleError(msg)
        self._head = head
        self._last_key = last_key

    def peek_ts(self) -> TimestampNs | None:
        """Timestamp of the next event; ``None`` when the feed is exhausted."""
        self._fill()
        return None if self._head is None else self._head.ts

    def peek(self) -> Event | None:
        """The next event without consuming it (``None`` when exhausted).

        Same I9 check as ``peek_ts``. Used by resume to compare the feed's
        events against a checkpoint cursor; the strategy never sees it.
        """
        self._fill()
        return self._head

    def pop(self) -> Event:
        """Remove and return the next event. Raises ``IndexError`` when empty."""
        self._fill()
        if self._head is None:
            msg = "pop from an exhausted feed"
            raise IndexError(msg)
        event, self._head = self._head, None
        self._last_key = (int(event.ts), event.seq, str(event.id))
        return event

    def _fill(self) -> None:
        if self._head is not None or self._exhausted:
            return
        try:
            event = next(self._events)
        except StopIteration:
            self._exhausted = True
            return
        self._check_order(event)
        self._head = event

    def _check_order(self, event: Event) -> None:
        last = self._last_key
        if last is None:
            return
        last_ts, last_seq, last_id = last
        if event.ts < last_ts or (event.ts == last_ts and event.seq <= last_seq):
            msg = (
                f"feed ordering violated (I9): event {event.id} "
                f"(symbol={getattr(event, 'symbol', None)}, ts={event.ts}, seq={event.seq}) "
                f"follows {last_id} (ts={last_ts}, seq={last_seq}). DataFeed.events() must "
                "yield non-decreasing ts, ties broken by strictly increasing seq; fix the "
                "feed, the engine will not reorder events."
            )
            raise InvariantViolation(msg)
