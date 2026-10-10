"""The single monotonic simulation clock.

Nothing inside the simulation reads wall-clock time; every component reads
this clock, which only the event loop advances.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crucible.core import checkpoint as ckpt
from crucible.core.errors import InvariantViolation
from crucible.core.types import TimestampNs

if TYPE_CHECKING:
    from collections.abc import Mapping


class SimulationClock:
    """Monotonic simulation time. Advancing backward raises: time reversal is
    a determinism bug, never a recoverable condition."""

    def __init__(self, start: TimestampNs) -> None:
        self._now = start

    @property
    def now(self) -> TimestampNs:
        return self._now

    def advance(self, ts: TimestampNs) -> None:
        if ts < self._now:
            msg = (
                f"clock cannot go backward: now={self._now}, requested={ts}. "
                "An event was enqueued in the past; fix the producer's timestamps."
            )
            raise InvariantViolation(msg)
        self._now = ts

    def snapshot(self) -> dict[str, object]:
        """The current simulation time (UTC ns)."""
        return {"now": int(self._now)}

    def restore(self, state: Mapping[str, object]) -> None:
        """Sets the clock to a checkpointed instant, bypassing the monotonic
        guard: a resume legitimately starts from a saved time (it is not a
        reversal within a run, which ``advance`` still refuses)."""
        self._now = TimestampNs(ckpt.field(state, "now", int))
