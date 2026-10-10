"""Event immutability, protocol conformance, and clock monotonicity."""

from __future__ import annotations

import dataclasses

import pytest

from crucible.core.clock import SimulationClock
from crucible.core.errors import InvariantViolation
from crucible.core.events import BarEvent, sequence_counter
from crucible.core.interfaces import Event
from crucible.core.types import EventId, Symbol, TimestampNs


def _bar(ts: int = 1_000, seq: int = 0) -> BarEvent:
    return BarEvent(
        id=EventId(f"bar-{seq}"),
        ts=TimestampNs(ts),
        seq=seq,
        symbol=Symbol("AAA"),
        event_time=TimestampNs(ts),
        open_time=TimestampNs(max(ts - 100, 0)),
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        volume=1000.0,
    )


def test_events_are_immutable() -> None:
    bar = _bar()
    with pytest.raises(dataclasses.FrozenInstanceError):
        bar.close = 99.0  # type: ignore[misc]  # the freeze under test


def test_bar_event_satisfies_event_protocol() -> None:
    assert isinstance(_bar(), Event)


def test_sequence_counter_is_monotonic() -> None:
    counter = sequence_counter()
    assert [next(counter) for _ in range(3)] == [0, 1, 2]


def test_clock_advances_forward_and_holds() -> None:
    clock = SimulationClock(TimestampNs(0))
    clock.advance(TimestampNs(5))
    clock.advance(TimestampNs(5))  # same instant is fine
    assert clock.now == 5


def test_clock_refuses_to_go_backward() -> None:
    clock = SimulationClock(TimestampNs(10))
    with pytest.raises(InvariantViolation, match="backward"):
        clock.advance(TimestampNs(9))
