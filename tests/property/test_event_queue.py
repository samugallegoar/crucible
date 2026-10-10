"""Property: the event queue pops in strict (ts, seq) order — invariant I9."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from crucible.core.events import BarEvent, sequence_counter
from crucible.core.queue import DeterministicEventQueue
from crucible.core.types import EventId, Symbol, TimestampNs


def _bar(ts: int, seq: int) -> BarEvent:
    return BarEvent(
        id=EventId(f"e{seq}"),
        ts=TimestampNs(ts),
        seq=seq,
        symbol=Symbol("AAA"),
        event_time=TimestampNs(ts),
        open_time=TimestampNs(max(ts - 1, 0)),
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=0.0,
    )


@given(st.lists(st.integers(min_value=0, max_value=1_000), max_size=200))
def test_pops_are_sorted_by_ts_then_seq(timestamps: list[int]) -> None:
    counter = sequence_counter()
    events = [_bar(ts, next(counter)) for ts in timestamps]

    queue = DeterministicEventQueue()
    for event in events:
        queue.push(event)

    popped = [queue.pop() for _ in range(len(queue))]
    keys = [(e.ts, e.seq) for e in popped]
    assert keys == sorted(keys)
    # ties on ts resolve in creation (seq) order — determinism, not luck
    assert len(popped) == len(events)


@given(st.lists(st.integers(min_value=0, max_value=50), min_size=1, max_size=100))
def test_identical_inputs_pop_identically(timestamps: list[int]) -> None:
    def run() -> list[str]:
        counter = sequence_counter()
        queue = DeterministicEventQueue()
        for ts in timestamps:
            queue.push(_bar(ts, next(counter)))
        return [str(queue.pop().id) for _ in range(len(queue))]

    assert run() == run()
