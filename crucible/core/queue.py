"""Deterministic event queue: strict ``(ts, seq)`` ordering (invariant I9)."""

from __future__ import annotations

import heapq
from collections.abc import Mapping

from crucible.core import checkpoint as ckpt
from crucible.core.errors import CheckpointError, InvariantViolation
from crucible.core.interfaces import Event
from crucible.core.types import TimestampNs


class DeterministicEventQueue:
    """Priority queue keyed ``(ts, seq)``.

    ``seq`` comes from the engine's single sequence counter at event creation,
    so identical inputs produce identical pop order. Popping verifies
    non-decreasing timestamps and raises ``InvariantViolation`` otherwise —
    the queue is where I9 is enforced, not documented.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[TimestampNs, int, Event]] = []
        self._last_popped: tuple[TimestampNs, int] | None = None

    def push(self, event: Event) -> None:
        heapq.heappush(self._heap, (event.ts, event.seq, event))

    def pop(self) -> Event:
        ts, seq, event = heapq.heappop(self._heap)
        if self._last_popped is not None and (ts, seq) < self._last_popped:
            msg = (
                f"event queue ordering violated: popped (ts={ts}, seq={seq}) after "
                f"{self._last_popped}. Duplicate seq or an event pushed into the past."
            )
            raise InvariantViolation(msg)
        self._last_popped = (ts, seq)
        return event

    def peek_ts(self) -> TimestampNs | None:
        """Timestamp of the next event without removing it; None when empty."""
        if not self._heap:
            return None
        return self._heap[0][0]

    def __len__(self) -> int:
        return len(self._heap)

    def snapshot(self) -> dict[str, object]:
        """Pending events in pop order plus the I9 watermark."""
        events = [event for _, _, event in sorted(self._heap, key=lambda item: (item[0], item[1]))]
        last = (
            None if self._last_popped is None else (int(self._last_popped[0]), self._last_popped[1])
        )
        return {"events": events, "last_popped": last}

    def restore(self, state: Mapping[str, object]) -> None:
        """Rebuilds the heap (pop order is fully determined by the unique
        ``(ts, seq)`` keys) and the I9 watermark. A refusal leaves the queue
        exactly as it was: everything is built and validated locally first
        (ADR-0048)."""
        heap: list[tuple[TimestampNs, int, Event]] = []
        for raw in ckpt.field_list(state, "events"):
            if not isinstance(raw, Event):
                msg = f"checkpoint queue entry must be an event, got {type(raw).__name__}"
                raise CheckpointError(msg)
            heapq.heappush(heap, (raw.ts, raw.seq, raw))
        last = ckpt.optional_field(state, "last_popped", tuple)
        last_popped: tuple[TimestampNs, int] | None = None
        if last is not None:
            if len(last) != 2 or not all(
                isinstance(part, int) and not isinstance(part, bool) for part in last
            ):
                msg = f"checkpoint queue last_popped must be (ts, seq), got {last!r}"
                raise CheckpointError(msg)
            last_popped = (TimestampNs(last[0]), last[1])
        self._heap = heap
        self._last_popped = last_popped
