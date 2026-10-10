"""Core Protocols: events, clock, deterministic queue.

Timing semantics: every event carries the simulation timestamp at which it
becomes true (`ts`) and a monotonically assigned `seq` that breaks timestamp
ties deterministically. Identical inputs must produce identical
event order, always.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from crucible.core.types import EventId, TimestampNs


@runtime_checkable
class Event(Protocol):
    """An immutable occurrence in simulation time.

    Concrete events are frozen, slotted dataclasses (ADR-0006). Nothing may
    mutate an event after creation; the members are read-only by contract.
    """

    @property
    def id(self) -> EventId: ...

    @property
    def ts(self) -> TimestampNs: ...

    @property
    def seq(self) -> int: ...


class MarketEvent(Event, Protocol):
    """A bar, trade, quote, or book snapshot becoming known at ``ts``."""


class DataEvent(Event, Protocol):
    """Fundamental/alternative data becoming *available* at ``ts``."""


class SignalEvent(Event, Protocol):
    """A strategy-emitted signal."""


class OrderEvent(Event, Protocol):
    """An order being submitted to the (simulated) market."""


class OrderUpdateEvent(Event, Protocol):
    """An order state change (accepted, cancelled, rejected, expired...)."""


class FillEvent(Event, Protocol):
    """An execution: quantity at a price, at a time the order could have reached."""


class CorporateActionEvent(Event, Protocol):
    """A corporate action taking effect at ``ts``."""


class ClockEvent(Event, Protocol):
    """A session boundary: open, close, settlement."""


class RiskEvent(Event, Protocol):
    """A logged risk-engine action: reject, resize, flatten, halt."""


class Clock(Protocol):
    """The single monotonic simulation clock.

    Every component reads time from here; nothing reads wall-clock time inside
    the simulation (AGENTS.md §9).
    """

    @property
    def now(self) -> TimestampNs:
        """Current simulation time. Knowable: always; it defines 'now'."""
        ...


class EventQueue(Protocol):
    """Deterministic priority queue keyed ``(ts, seq)``.

    Popping must yield non-decreasing timestamps; ties break by ``seq``.
    """

    def push(self, event: Event) -> None: ...

    def pop(self) -> Event:
        """Remove and return the next event. Raises ``IndexError`` when empty."""
        ...

    def __len__(self) -> int: ...


@runtime_checkable
class Snapshottable(Protocol):
    """A component whose mutable run state can be checkpointed (E7, ADR-0041).

    ``snapshot()`` returns a dict built only from values the checkpoint codec
    supports (see ``crucible.core.checkpoint``); it never returns JSON and
    never includes configuration (setup is verified by fingerprint, not
    stored per component). ``restore(state)`` mutates the object **in
    place**: other components hold references to it. Restore is a resume
    path, not a normal operation, and may bypass runtime guards that only
    make sense within one uninterrupted run; it raises ``CheckpointError`` on
    malformed state.
    """

    def snapshot(self) -> dict[str, object]: ...

    def restore(self, state: Mapping[str, object]) -> None: ...
