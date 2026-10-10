"""Snapshot/restore for the clock, queue, logger and ledger (E7, ADR-0041).

Each test goes through the real codec and JSON text, so it proves the
snapshot uses only codec-supported values.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from crucible.accounting.ledger import InMemoryLedger, TransactionRecord
from crucible.core.checkpoint import canonical_json, decode, encode
from crucible.core.clock import SimulationClock
from crucible.core.errors import CheckpointError, InvariantViolation
from crucible.core.events import BarEvent
from crucible.core.interfaces import Snapshottable
from crucible.core.logging import RunLogger
from crucible.core.queue import DeterministicEventQueue
from crucible.core.types import (
    Currency,
    EventId,
    Symbol,
    TimestampNs,
    TransactionType,
)


def _through_json(state: dict[str, object]) -> dict[str, object]:
    out = decode(json.loads(canonical_json(encode(state))))
    assert isinstance(out, dict)
    return out


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


def test_components_satisfy_the_protocol() -> None:
    clock = SimulationClock(TimestampNs(0))
    assert isinstance(clock, Snapshottable)
    assert isinstance(DeterministicEventQueue(), Snapshottable)
    assert isinstance(RunLogger(clock), Snapshottable)
    ledger = InMemoryLedger({Currency("USD"): Decimal("1")}, TimestampNs(0))
    assert isinstance(ledger, Snapshottable)


def test_clock_restores_time_even_though_it_is_a_jump() -> None:
    clock = SimulationClock(TimestampNs(0))
    clock.advance(TimestampNs(500))
    state = _through_json(clock.snapshot())
    fresh = SimulationClock(TimestampNs(0))
    fresh.restore(state)
    assert fresh.now == 500
    with pytest.raises(InvariantViolation):
        fresh.advance(TimestampNs(499))  # the guard is still live after restore


def test_queue_restores_events_pop_order_and_the_i9_watermark() -> None:
    queue = DeterministicEventQueue()
    for event in (_bar(3, 30, 2), _bar(1, 10, 0), _bar(2, 20, 1), _bar(4, 20, 5)):
        queue.push(event)
    assert queue.pop().seq == 0  # ts=10 popped; watermark (10, 0)
    state = _through_json(queue.snapshot())

    fresh = DeterministicEventQueue()
    fresh.restore(state)
    assert len(fresh) == 3
    assert fresh.peek_ts() == 20
    assert [fresh.pop().seq for _ in range(3)] == [1, 5, 2]

    again = DeterministicEventQueue()
    again.restore(state)
    again.push(_bar(9, 5, 9))  # earlier than the restored watermark
    with pytest.raises(InvariantViolation, match="ordering violated"):
        again.pop()


def test_logger_restores_entries_in_order() -> None:
    clock = SimulationClock(TimestampNs(0))
    log = RunLogger(clock)
    log.info("first", n=1, amount=Decimal("2.5"))
    clock.advance(TimestampNs(7))
    log.warning("second", ok=True)
    state = _through_json(log.snapshot())

    fresh = RunLogger(SimulationClock(TimestampNs(7)))
    fresh.restore(state)
    assert fresh.entries == log.entries
    fresh.info("third")
    assert len(fresh.entries) == 3


def _txn(n: int, ts: int, amount: str) -> TransactionRecord:
    return TransactionRecord(
        id=f"T-{n:08d}",
        ts=TimestampNs(ts),
        type=TransactionType.FILL,
        amounts={Currency("USD"): Decimal(amount)},
        refs={"order_id": "O-00000000"},
        symbol=Symbol("AAA"),
        qty=Decimal("1"),
        price=Decimal("10"),
    )


def test_ledger_restores_transactions_and_folds_identically() -> None:
    ledger = InMemoryLedger({Currency("USD"): Decimal("1000")}, TimestampNs(0))
    ledger.append(_txn(1, 10, "-10"))
    ledger.append(_txn(2, 20, "-20"))
    state = _through_json(ledger.snapshot())

    fresh = InMemoryLedger({Currency("USD"): Decimal("1000")}, TimestampNs(0))
    fresh.restore(state)
    assert list(fresh) == list(ledger)
    assert fresh.fold().cash == ledger.fold().cash
    fresh.append(_txn(3, 20, "-1"))  # append order check still works after restore
    with pytest.raises(InvariantViolation):
        fresh.append(_txn(4, 5, "-1"))


def test_restore_refuses_malformed_state() -> None:
    ledger = InMemoryLedger({Currency("USD"): Decimal("1")}, TimestampNs(0))
    with pytest.raises(CheckpointError, match="txns"):
        ledger.restore({})
    with pytest.raises(CheckpointError, match="TransactionRecord"):
        ledger.restore({"txns": ["not a record"]})
