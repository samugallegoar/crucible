"""A refused restore must leave the component exactly as it was (ADR-0048)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from crucible.core.errors import CheckpointError
from crucible.core.events import BarEvent
from crucible.core.queue import DeterministicEventQueue
from crucible.core.types import Currency, EventId, Symbol, TimestampNs
from crucible.risk.engine import CompositeRiskEngine
from crucible.risk.limits import DailyLossFlattenLimit, DrawdownHaltLimit

USD = Currency("USD")


def _bar(n: int, ts: int, seq: int) -> BarEvent:
    return BarEvent(
        id=EventId(f"E-{n:08d}"),
        ts=TimestampNs(ts),
        seq=seq,
        symbol=Symbol("AAA"),
        event_time=TimestampNs(ts),
        open_time=TimestampNs(ts),
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=1.0,
    )


class _Portfolio:
    def __init__(self, equity: str) -> None:
        self._equity = Decimal(equity)

    def equity(self, base: Currency) -> Decimal:
        return self._equity


def test_a_failed_queue_restore_leaves_the_queue_untouched() -> None:
    queue = DeterministicEventQueue()
    queue.push(_bar(1, 10, 0))
    before = queue.snapshot()
    bad = {"events": [_bar(2, 20, 1), "not an event"], "last_popped": None}
    with pytest.raises(CheckpointError):
        queue.restore(bad)
    assert queue.snapshot() == before
    assert len(queue) == 1


def test_a_failed_composite_restore_rolls_back_limits_already_restored() -> None:
    drawdown = DrawdownHaltLimit(0.1)
    daily = DailyLossFlattenLimit(0.05)
    engine = CompositeRiskEngine(USD, mark_limits=[drawdown, daily])
    drawdown.check(_Portfolio("1000"), TimestampNs(1), USD)  # peak 1000
    before = engine.snapshot()
    bad = {
        "pre_trade": [],
        "mark": [{"peak": Decimal("5000")}, {"day": "not-an-int", "day_start_equity": None}],
    }
    with pytest.raises(CheckpointError):
        engine.restore(bad)
    assert engine.snapshot() == before


def test_queue_restore_refuses_a_bool_in_last_popped() -> None:
    queue = DeterministicEventQueue()
    with pytest.raises(CheckpointError, match="last_popped"):
        queue.restore({"events": [], "last_popped": (True, 1)})
